// VPN Engine — полноценный VPN через TUN (как V2Ray / HAPP / Hiddify)
//
// Архитектура:
//   VLESS/Trojan  → xray.exe SOCKS5:10808 → tun2socks → WinTUN (MilkyVPN-TUN)
//   NaiveProxy    → naive.exe SOCKS5:10808 → tun2socks → WinTUN (MilkyVPN-TUN)
//   AmneziaWG     → amneziawg.exe /installtunnelservice
//
// ВАЖНО: конфиги пишутся в C:\ProgramData\MilkyVPN\ (ASCII-путь, без кириллицы!)
//
// Cascade архитектура:
//   Клиент → RU сервер (entry_ip из API) → EU сервер (реальный VPN)
//   API уже отдаёт server_ip = entry_ip:
//     direct  → EU IP напрямую
//     cascade → RU IP (entry point)
//   Для маршрутизации: server_ip роутим напрямую (не через TUN), иначе петля.
//   Для VLESS cascade: xray коннектится к RU серверу → он форвардит на EU.
//   Поэтому bypass-маршрут = server_ip (RU для cascade, EU для direct).

import 'dart:async';
import 'dart:io';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import '../models/connection.dart';
import '../utils/constants.dart';
import 'engine_downloader.dart';

enum EngineType { xray, awg, naive }

class VpnEngine {
  VpnEngine._();
  static final VpnEngine instance = VpnEngine._();

  Process?    _proxyProcess;
  Process?    _tunProcess;
  EngineType? _activeEngine;
  String?     _tempConfigPath;
  String?     _awgConfPath;
  String?     _awgTunnelName;
  String?     _vpnServerIp;   // IP который роутим напрямую (bypass)
  String?     _originalGateway;
  bool        _routesAdded = false;

  static const _tunName    = 'MilkyVPN-TUN';
  static const _tunAddr    = '10.8.0.1';      // IP самого TUN адаптера
  static const _tunMask    = '255.255.255.0';
  static const _tunGateway = '10.8.0.1';      // шлюз через TUN (= его IP)
  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  // Директория для конфигов — ASCII путь, xray не падает
  static const _configDir = r'C:\ProgramData\MilkyVPN';

  final ValueNotifier<VpnStatus> status    = ValueNotifier(VpnStatus.disconnected);
  final ValueNotifier<String?>   lastError = ValueNotifier(null);

  bool get isConnected => status.value == VpnStatus.connected;

  // ═══════════════════════════════════════════════════════
  // Public API
  // ═══════════════════════════════════════════════════════

  Future<void> connect(VpnConnection conn) async {
    if (status.value == VpnStatus.connected ||
        status.value == VpnStatus.connecting) {
      await disconnect();
    }
    status.value    = VpnStatus.connecting;
    lastError.value = null;

    try {
      switch (conn.protocol) {
        case Protocol.vlessReality:
        case Protocol.trojan:
          await _startXrayWithTun(conn);
          break;
        case Protocol.amneziaWg:
          await _startAwg(conn);
          break;
        case Protocol.naiveProxy:
          await _startNaiveWithTun(conn);
          break;
        case Protocol.unknown:
          throw VpnEngineException('Неподдерживаемый протокол: ${conn.protocol}');
      }
    } catch (e) {
      status.value    = VpnStatus.error;
      lastError.value = e.toString().replaceFirst('VpnEngineException: ', '');
      unawaited(_forceCleanup());
      rethrow;
    }
  }

  Future<void> disconnect() async {
    if (status.value == VpnStatus.disconnected) return;
    status.value = VpnStatus.disconnecting;
    try {
      await _forceCleanup();
    } finally {
      status.value = VpnStatus.disconnected;
    }
  }

  // ═══════════════════════════════════════════════════════
  // VLESS / Trojan → xray → tun2socks → TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _startXrayWithTun(VpnConnection conn) async {
    final engineDir = await _engineDir();
    final xrayPath  = p.join(engineDir, 'xray.exe');
    final t2sPath   = p.join(engineDir, 'tun2socks.exe');

    _checkFile(xrayPath, 'xray.exe');
    _checkFile(t2sPath,  'tun2socks.exe');

    // server_ip из API = entry point:
    //   direct  → EU IP
    //   cascade → RU IP (бэкенд уже заменил)
    // Этот IP должен идти напрямую (bypass), чтобы не было петли
    _vpnServerIp = conn.serverIp;

    final configPath = await _writeConfig(
        'xray_${conn.id}.json', jsonEncode(_buildXrayConfig(conn)));
    _tempConfigPath = configPath;

    final logBuf = StringBuffer();

    _proxyProcess = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      workingDirectory: engineDir,
      runInShell: false,
    );
    _activeEngine = EngineType.xray;
    _proxyProcess!.stdout.transform(utf8.decoder).listen(logBuf.write);
    _proxyProcess!.stderr.transform(utf8.decoder).listen(logBuf.write);

    await Future.delayed(const Duration(seconds: 2));
    await _assertAlive(_proxyProcess!, 'xray.exe', logBuf);

    await _startTun2socks(engineDir);
    await _setupRoutes(conn.serverIp);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        status.value    = VpnStatus.error;
        lastError.value = 'xray завершился (код $code)'
            '${_tail(logBuf.toString(), 600).isNotEmpty ? ":\n${_tail(logBuf.toString(), 600)}" : ""}'
            '${_xrayHint(code)}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // NaiveProxy → naive → tun2socks → TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _startNaiveWithTun(VpnConnection conn) async {
    final engineDir = await _engineDir();
    final naivePath = p.join(engineDir, 'naive.exe');
    final t2sPath   = p.join(engineDir, 'tun2socks.exe');

    _checkFile(naivePath, 'naive.exe');
    _checkFile(t2sPath,   'tun2socks.exe');

    _vpnServerIp = conn.serverIp;

    // Убиваем старые экземпляры (порт мог остаться занят)
    await _killByName('naive.exe');
    await Future.delayed(const Duration(milliseconds: 300));

    final cfgPath = await _writeConfig(
        'naive_${conn.id}.json', _buildNaiveConfig(conn));
    _tempConfigPath = cfgPath;

    final logBuf = StringBuffer();

    _proxyProcess = await Process.start(
      naivePath,
      ['--config=$cfgPath'],
      runInShell: false,
    );
    _activeEngine = EngineType.naive;
    _proxyProcess!.stdout.transform(utf8.decoder).listen(logBuf.write);
    _proxyProcess!.stderr.transform(utf8.decoder).listen(logBuf.write);

    await Future.delayed(const Duration(milliseconds: 1500));
    await _assertAlive(_proxyProcess!, 'naive.exe', logBuf);

    await _startTun2socks(engineDir);
    await _setupRoutes(conn.serverIp);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        status.value    = VpnStatus.error;
        lastError.value = 'naive завершился (код $code)'
            '${_tail(logBuf.toString(), 600).isNotEmpty ? ":\n${_tail(logBuf.toString(), 600)}" : ""}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // tun2socks — TUN адаптер поверх SOCKS5
  // ═══════════════════════════════════════════════════════

  Future<void> _startTun2socks(String engineDir) async {
    // Убиваем старый экземпляр если остался
    await _killByName('tun2socks.exe');
    await Future.delayed(const Duration(milliseconds: 300));

    final t2sPath = p.join(engineDir, 'tun2socks.exe');
    final logBuf  = StringBuffer();

    // wintun.dll должна быть в том же каталоге что и tun2socks.exe
    // Проверяем что она там есть
    final wintunPath = p.join(engineDir, 'wintun.dll');
    if (!File(wintunPath).existsSync()) {
      throw VpnEngineException(
        'wintun.dll не найден в папке engines.\n'
        'Удалите папку engines и перезапустите приложение для переустановки.\n'
        'Путь: $wintunPath',
      );
    }

    _tunProcess = await Process.start(
      t2sPath,
      [
        '--device',   'tun://$_tunName',
        '--proxy',    'socks5://127.0.0.1:${AppConstants.xraySocksPort}',
        '--loglevel', 'info',
      ],
      workingDirectory: engineDir, // wintun.dll рядом — обязательно!
      runInShell: false,
    );
    _tunProcess!.stdout.transform(utf8.decoder).listen(logBuf.write);
    _tunProcess!.stderr.transform(utf8.decoder).listen(logBuf.write);

    // Ждём пока WinTUN создаст адаптер (может занять 3-5 сек)
    await Future.delayed(const Duration(seconds: 4));
    await _assertAlive(_tunProcess!, 'tun2socks.exe', logBuf);

    _tunProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        status.value    = VpnStatus.error;
        lastError.value = 'tun2socks завершился (код $code)'
            '${_tail(logBuf.toString(), 500).isNotEmpty ? ":\n${_tail(logBuf.toString(), 500)}" : ""}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // Маршруты — весь трафик через TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _setupRoutes(String serverIp) async {
    try {
      // 1. Получаем текущий шлюз ДО изменения маршрутов
      _originalGateway = await _getDefaultGateway();
      if (_originalGateway == null || _originalGateway!.isEmpty) {
        throw VpnEngineException(
            'Не удалось определить шлюз по умолчанию.\nПроверьте сетевое подключение.');
      }

      // 2. Назначаем IP TUN адаптеру
      final netshR = await Process.run('netsh', [
        'interface', 'ip', 'set', 'address',
        'name=$_tunName', 'static', _tunAddr, _tunMask,
      ], runInShell: false);
      debugPrint('[VPN] netsh set address: ${netshR.stdout} ${netshR.stderr}');

      await Future.delayed(const Duration(milliseconds: 800));

      // 3. VPN сервер (entry point) — через оригинальный шлюз (иначе петля!)
      //    server_ip = entry point (RU для cascade, EU для direct)
      await Process.run('route', [
        'add', serverIp, 'mask', '255.255.255.255',
        _originalGateway!, 'metric', '1',
      ], runInShell: false);

      // 4. Весь остальной трафик — через TUN
      //    Два маршрута /1 перекрывают дефолтный /0 без его удаления
      await Process.run('route', [
        'add', '0.0.0.0', 'mask', '128.0.0.0', _tunGateway, 'metric', '5',
      ], runInShell: false);
      await Process.run('route', [
        'add', '128.0.0.0', 'mask', '128.0.0.0', _tunGateway, 'metric', '5',
      ], runInShell: false);

      // 5. DNS через Cloudflare на TUN интерфейс (нет DNS-утечек)
      await Process.run('netsh', [
        'interface', 'ip', 'set', 'dns',
        'name=$_tunName', 'static', '1.1.1.1',
      ], runInShell: false);

      _routesAdded = true;
      debugPrint('[VPN] Routes up. Entry=$serverIp bypass via $_originalGateway, rest → TUN $_tunGateway');
    } catch (e) {
      await _removeRoutes();
      rethrow;
    }
  }

  Future<void> _removeRoutes() async {
    if (!_routesAdded) return;
    try {
      if (_vpnServerIp != null) {
        await Process.run('route', [
          'delete', _vpnServerIp!, 'mask', '255.255.255.255',
        ], runInShell: false);
      }
      await Process.run('route', ['delete', '0.0.0.0',   'mask', '128.0.0.0'],
          runInShell: false);
      await Process.run('route', ['delete', '128.0.0.0', 'mask', '128.0.0.0'],
          runInShell: false);
      debugPrint('[VPN] Routes removed');
    } catch (e) {
      debugPrint('[VPN] _removeRoutes error (non-fatal): $e');
    } finally {
      _routesAdded     = false;
      _originalGateway = null;
      _vpnServerIp     = null;
    }
  }

  Future<String?> _getDefaultGateway() async {
    final r = await Process.run('powershell', [
      '-NoProfile', '-Command',
      '(Get-NetRoute -DestinationPrefix "0.0.0.0/0" | '
      'Sort-Object RouteMetric | '
      'Select-Object -First 1).NextHop',
    ], runInShell: false);
    final gw = r.stdout.toString().trim();
    return gw.isEmpty ? null : gw;
  }

  // ═══════════════════════════════════════════════════════
  // AmneziaWG
  // ═══════════════════════════════════════════════════════

  Future<void> _startAwg(VpnConnection conn) async {
    if (!File(_awgExePath).existsSync()) {
      throw VpnEngineException(
          'AmneziaWG не установлен.\nПерезапустите приложение — установка произойдёт автоматически.');
    }

    // config_json из API = config_text из БД = полный WG конфиг
    // Убираем строку "Name = ..." которую amneziawg.exe не принимает
    String confText;
    if (conn.configJson != null && conn.configJson!.contains('[Interface]')) {
      confText = _sanitizeAwgConf(conn.configJson!);
    } else {
      confText = _buildAwgConfig(conn);
    }

    final tunnelName = 'MilkyVPN${conn.id}';
    _awgTunnelName   = tunnelName;

    final confPath = await _writeConfig('$tunnelName.conf', confText);
    _awgConfPath    = confPath;
    _tempConfigPath = confPath;

    // Убираем старый туннель (если был)
    await _runHidden(_awgExePath, ['/uninstalltunnelservice', tunnelName]);
    await Future.delayed(const Duration(milliseconds: 800));

    // Устанавливаем туннель
    final r = await _runHidden(_awgExePath, ['/installtunnelservice', confPath]);
    if (r.exitCode != 0) {
      final err = '${r.stdout}\n${r.stderr}'.trim();
      throw VpnEngineException(
          'AWG: ошибка установки (код ${r.exitCode})\n$err'
          '${err.toLowerCase().contains('access') ? "\n⚠️ Запустите от имени Администратора!" : ""}');
    }

    // Ждём запуска сервиса
    await Future.delayed(const Duration(seconds: 3));

    // Проверяем Windows-сервис
    final scName = 'AmneziaWGTunnel\$$tunnelName';
    final sc     = await Process.run('sc', ['query', scName], runInShell: true);
    final scOut  = sc.stdout.toString();

    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      final logR = await Process.run(
          'powershell', ['-NoProfile', '-Command',
           'Get-EventLog -LogName System -Source "AmneziaWG*" -Newest 5 '
           '| Select-Object -ExpandProperty Message'],
          runInShell: false);
      final logMsg = logR.stdout.toString().trim();
      throw VpnEngineException(
          'AWG туннель не запустился.\n'
          'SC вывод: $scOut'
          '${logMsg.isNotEmpty ? "\nLog: $logMsg" : ""}');
    }

    _activeEngine = EngineType.awg;
    status.value  = VpnStatus.connected;
    _monitorAwg(tunnelName);
  }

  /// Убирает поля которые amneziawg.exe не принимает (Name = ...)
  String _sanitizeAwgConf(String raw) {
    return raw
        .split('\n')
        .where((line) {
          final t = line.trim();
          return !t.startsWith('Name =') && !t.startsWith('Name=');
        })
        .join('\n');
  }

  void _monitorAwg(String tunnelName) {
    Future.delayed(const Duration(seconds: 5), () async {
      if (status.value != VpnStatus.connected || _activeEngine != EngineType.awg) return;
      try {
        final r = await Process.run(
            'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'], runInShell: true);
        if (!r.stdout.toString().contains('RUNNING')) {
          status.value    = VpnStatus.error;
          lastError.value = 'AWG туннель остановился неожиданно';
          unawaited(_forceCleanup());
          return;
        }
      } catch (_) {}
      _monitorAwg(tunnelName);
    });
  }

  // ═══════════════════════════════════════════════════════
  // Config builders
  // ═══════════════════════════════════════════════════════

  Map<String, dynamic> _buildXrayConfig(VpnConnection conn) {
    final outbound = <String, dynamic>{};

    // server_ip = entry_ip из API:
    //   direct  → EU IP (подключаемся напрямую к EU)
    //   cascade → RU IP (подключаемся к RU, он форвардит на EU)
    // В обоих случаях просто используем conn.serverIp как адрес сервера

    if (conn.protocol == Protocol.vlessReality) {
      outbound['protocol'] = 'vless';
      outbound['settings'] = {
        'vnext': [{
          'address': conn.serverIp,
          'port':    conn.port,
          'users': [{
            'id':         conn.uuid ?? '',
            'flow':       'xtls-rprx-vision',
            'encryption': 'none',
          }],
        }],
      };
      outbound['streamSettings'] = {
        'network':  'tcp',
        'security': 'reality',
        'realitySettings': {
          'fingerprint': 'chrome',
          'serverName':  conn.realityServerName ?? 'www.microsoft.com',
          'publicKey':   conn.realityPublicKey  ?? '',
          'shortId':     conn.realityShortId    ?? '',
          'spiderX':     '/',
        },
      };
    } else {
      // Trojan
      outbound['protocol'] = 'trojan';
      outbound['settings'] = {
        'servers': [{
          'address':  conn.serverIp,
          'port':     conn.port,
          'password': conn.password ?? '',
        }],
      };
      outbound['streamSettings'] = {
        'network':    'tcp',
        'security':   'tls',
        'tlsSettings': {'serverName': conn.serverIp},
      };
    }

    return {
      'log': {'loglevel': 'warning'},
      'inbounds': [
        {
          'tag':      'socks',
          'listen':   '127.0.0.1',
          'port':     AppConstants.xraySocksPort,
          'protocol': 'socks',
          'settings': {'auth': 'noauth', 'udp': true},
        },
      ],
      'outbounds': [
        {...outbound, 'tag': 'proxy'},
        {'tag': 'direct', 'protocol': 'freedom'},
        {'tag': 'block',  'protocol': 'blackhole'},
      ],
      'routing': {
        'domainStrategy': 'IPIfNonMatch',
        'rules': [
          // Loopback и приватные сети — напрямую (не через proxy)
          {'type': 'field', 'ip': ['geoip:private'], 'outboundTag': 'direct'},
          // Всё остальное — через VPN сервер
          {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'},
        ],
      },
    };
  }

  /// NaiveProxy конфиг — строим из полей БД, НЕ из config_json
  /// (config_json содержит порт 443 без TLS-сертификата — не работает)
  /// API уже отдаёт правильный server_ip:
  ///   direct  → EU IP,  port=2096
  ///   cascade → RU IP,  port=8443
  String _buildNaiveConfig(VpnConnection conn) {
    final pass = conn.password ?? '';
    return jsonEncode({
      'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
      'proxy':  'https://admin:$pass@${conn.serverIp}:${conn.port}',
      'log':    '',
    });
  }

  String _buildAwgConfig(VpnConnection conn) {
    final jc   = conn.awgJunkPacketCount   ?? 4;
    final jmin = conn.awgJunkPacketMinSize ?? 40;
    final jmax = conn.awgJunkPacketMaxSize ?? 70;
    return '[Interface]\n'
        'PrivateKey = ${conn.wgClientPrivateKey ?? ""}\n'
        'Address = ${conn.wgClientIp ?? "10.8.0.2"}/32\n'
        'DNS = 1.1.1.1, 8.8.8.8\n'
        'MTU = 1420\n'
        'Jc = $jc\n'
        'Jmin = $jmin\n'
        'Jmax = $jmax\n'
        'S1 = 50\n'
        'S2 = 100\n'
        'H1 = 1\n'
        'H2 = 2\n'
        'H3 = 3\n'
        'H4 = 4\n'
        '\n'
        '[Peer]\n'
        'PublicKey = ${conn.wgPublicKey ?? ""}\n'
        '${conn.wgPresharedKey != null ? "PresharedKey = ${conn.wgPresharedKey!}\n" : ""}'
        'Endpoint = ${conn.serverIp}:${conn.port}\n'
        'AllowedIPs = 0.0.0.0/0, ::/0\n'
        'PersistentKeepalive = 25\n';
  }

  String _xrayHint(int code) {
    switch (code) {
      case -1073741515: return '\n⚠️ Установите Visual C++ Redistributable 2019 x64';
      case 23:          return '\n⚠️ Путь к конфигу содержит недопустимые символы';
      case 1:           return '\n⚠️ Проверьте UUID и publicKey сервера';
      default:          return '';
    }
  }

  // ═══════════════════════════════════════════════════════
  // Cleanup — гарантированный откат
  // ═══════════════════════════════════════════════════════

  Future<void> _forceCleanup() async {
    // 1. Маршруты — первым делом, пока ещё знаем IP
    await _removeRoutes();

    // 2. tun2socks — taskkill (process.kill() на Windows ненадёжен)
    await _killByName('tun2socks.exe');
    if (_tunProcess != null) {
      try {
        await _tunProcess!.exitCode.timeout(const Duration(seconds: 2)).catchError((_) => -1);
      } catch (_) {}
      _tunProcess = null;
    }

    // 3. xray / naive — taskkill
    await _killByName('xray.exe');
    await _killByName('naive.exe');
    if (_proxyProcess != null) {
      try {
        await _proxyProcess!.exitCode.timeout(const Duration(seconds: 2)).catchError((_) => -1);
      } catch (_) {}
      _proxyProcess = null;
    }

    // 4. AWG туннель
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgExePath).existsSync()) {
          await _runHidden(_awgExePath, ['/uninstalltunnelservice', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    }

    // 5. Удаляем конфиги
    for (final path in [_tempConfigPath, _awgConfPath]) {
      if (path != null) {
        try { File(path).deleteSync(); } catch (_) {}
      }
    }
    _tempConfigPath = null;
    _awgConfPath    = null;
    _activeEngine   = null;
  }

  // ═══════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════

  /// Убивает все процессы с данным именем через taskkill /F
  /// (process.kill() на Windows отправляет CTRL_C_EVENT, который процессы игнорируют)
  Future<void> _killByName(String exeName) async {
    try {
      await Process.run(
        'taskkill', ['/F', '/IM', exeName],
        runInShell: false,
      );
    } catch (_) {}
    // Небольшая пауза чтобы ОС освободила порт/дескрипторы
    await Future.delayed(const Duration(milliseconds: 200));
  }

  void _checkFile(String path, String name) {
    if (!File(path).existsSync()) {
      throw VpnEngineException(
          '$name не найден. Удалите папку engines и перезапустите приложение.');
    }
  }

  Future<void> _assertAlive(Process proc, String name, StringBuffer buf) async {
    try {
      final code = await proc.exitCode.timeout(const Duration(milliseconds: 400));
      final log  = _tail(buf.toString(), 1200);
      throw VpnEngineException(
        '$name упал сразу после запуска (код $code)'
        '${log.isNotEmpty ? ":\n$log" : ""}',
      );
    } on TimeoutException {
      // Хорошо — процесс живёт
    }
  }

  /// Пишет конфиг в C:\ProgramData\MilkyVPN\ — ASCII путь, безопасен для xray
  Future<String> _writeConfig(String filename, String content) async {
    final dir = Directory(_configDir);
    if (!dir.existsSync()) dir.createSync(recursive: true);
    final file = File(p.join(_configDir, filename));
    await file.writeAsString(content, flush: true);
    return file.path;
  }

  Future<ProcessResult> _runHidden(String exe, List<String> args) =>
      Process.run(exe, args, runInShell: false);

  String _tail(String s, int maxLen) {
    s = s.trim();
    return s.length > maxLen ? '...' + s.substring(s.length - maxLen) : s;
  }

  Future<String> _engineDir() => EngineDownloader.instance.enginesDir;
}

class VpnEngineException implements Exception {
  final String message;
  VpnEngineException(this.message);
  @override
  String toString() => 'VpnEngineException: $message';
}
