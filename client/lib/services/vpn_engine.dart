// VPN Engine — полноценный VPN через TUN адаптер (как V2Ray / HAPP)
//
// Архитектура:
//   VLESS/Trojan  → xray.exe (SOCKS5 на 10808) → tun2socks → WinTUN адаптер
//   NaiveProxy    → naive.exe (SOCKS5 на 10808) → tun2socks → WinTUN адаптер
//   AmneziaWG     → amneziawg.exe /installtunnelservice (полноценный WG туннель)
//
// TUN адаптер перехватывает ВЕСЬ трафик машины (TCP + UDP) — настоящий VPN.
//
// Маршруты:
//   1. Трафик на VPN-сервер → через оригинальный шлюз (иначе петля)
//   2. Всё остальное       → через TUN адаптер (10.0.0.1)
//
// Cleanup гарантирован через try/finally + exitCode listener.

import 'dart:async';
import 'dart:io';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
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
  String?     _awgTunnelName;
  String?     _vpnServerIp;      // сохраняем чтобы убрать маршрут на cleanup
  String?     _originalGateway;  // оригинальный шлюз до подключения
  bool        _routesAdded = false;

  static const _tunName    = 'MilkyVPN-TUN';
  static const _tunAddr    = '10.0.0.1';     // IP адаптера
  static const _tunGateway = '10.0.0.1';     // шлюз через TUN
  static const _tunMask    = '255.255.255.0';

  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  final ValueNotifier<VpnStatus> status   = ValueNotifier(VpnStatus.disconnected);
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
  // VLESS / Trojan → xray SOCKS5 → tun2socks → TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _startXrayWithTun(VpnConnection conn) async {
    final engineDir = await _engineDir();
    final xrayPath  = p.join(engineDir, 'xray.exe');
    final t2sPath   = p.join(engineDir, 'tun2socks.exe');

    if (!File(xrayPath).existsSync()) {
      throw VpnEngineException(
          'xray.exe не найден. Удалите папку engines и перезапустите приложение.');
    }
    if (!File(t2sPath).existsSync()) {
      throw VpnEngineException(
          'tun2socks.exe не найден. Удалите папку engines и перезапустите приложение.');
    }

    _vpnServerIp = conn.serverIp;

    final config     = _buildXrayConfig(conn);
    final configPath = await _writeTempConfig('xray_config.json', jsonEncode(config));
    _tempConfigPath  = configPath;

    final logBuf = StringBuffer();

    // 1. Запускаем xray
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

    // 2. Запускаем tun2socks → создаёт TUN адаптер
    await _startTun2socks(engineDir);

    // 3. Настраиваем маршруты
    await _setupRoutes(conn.serverIp);

    status.value = VpnStatus.connected;

    // Мониторинг падения xray
    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final log = _tail(logBuf.toString(), 800);
        status.value    = VpnStatus.error;
        lastError.value = 'xray завершился (код $code)'
            '${log.isNotEmpty ? ":\n$log" : ""}'
            '${_xrayHint(code)}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // NaiveProxy → naive SOCKS5 → tun2socks → TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _startNaiveWithTun(VpnConnection conn) async {
    final engineDir = await _engineDir();
    final naivePath = p.join(engineDir, 'naive.exe');
    final t2sPath   = p.join(engineDir, 'tun2socks.exe');

    if (!File(naivePath).existsSync()) {
      throw VpnEngineException(
          'naive.exe не найден. Удалите папку engines и перезапустите.');
    }
    if (!File(t2sPath).existsSync()) {
      throw VpnEngineException(
          'tun2socks.exe не найден. Удалите папку engines и перезапустите.');
    }

    _vpnServerIp = conn.serverIp;

    final cfgContent = _buildNaiveConfig(conn);
    final cfgPath    = await _writeTempConfig('naive_config.json', cfgContent);
    _tempConfigPath  = cfgPath;

    final logBuf = StringBuffer();

    // 1. Запускаем naive
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

    // 2. tun2socks
    await _startTun2socks(engineDir);

    // 3. Маршруты
    await _setupRoutes(conn.serverIp);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final log = _tail(logBuf.toString(), 800);
        status.value    = VpnStatus.error;
        lastError.value = 'naive завершился (код $code)'
            '${log.isNotEmpty ? ":\n$log" : ""}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // tun2socks — поднимает TUN адаптер поверх SOCKS5
  // ═══════════════════════════════════════════════════════

  Future<void> _startTun2socks(String engineDir) async {
    final t2sPath   = p.join(engineDir, 'tun2socks.exe');
    final wintunDll = p.join(engineDir, 'wintun.dll');

    // wintun.dll должен лежать рядом с tun2socks.exe
    // (tun2socks ищет его в рабочей директории)
    final t2sLog = StringBuffer();

    _tunProcess = await Process.start(
      t2sPath,
      [
        '--device', 'tun://$_tunName',
        '--proxy',  'socks5://127.0.0.1:${AppConstants.xraySocksPort}',
        '--loglevel', 'info',
      ],
      workingDirectory: engineDir, // wintun.dll рядом
      environment:      {...Platform.environment, 'WINTUN_DLL': wintunDll},
      runInShell:       false,
    );

    _tunProcess!.stdout.transform(utf8.decoder).listen(t2sLog.write);
    _tunProcess!.stderr.transform(utf8.decoder).listen(t2sLog.write);

    // Ждём пока адаптер поднимется
    await Future.delayed(const Duration(seconds: 3));
    await _assertAlive(_tunProcess!, 'tun2socks.exe', t2sLog);

    // Мониторинг
    _tunProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final log = _tail(t2sLog.toString(), 600);
        status.value    = VpnStatus.error;
        lastError.value = 'tun2socks завершился (код $code)'
            '${log.isNotEmpty ? ":\n$log" : ""}';
        unawaited(_forceCleanup());
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // Маршруты — направляем весь трафик через TUN
  // ═══════════════════════════════════════════════════════

  Future<void> _setupRoutes(String serverIp) async {
    try {
      // 1. Сохраняем текущий шлюз
      _originalGateway = await _getDefaultGateway();
      debugPrint('Original gateway: $_originalGateway');

      if (_originalGateway == null || _originalGateway!.isEmpty) {
        throw VpnEngineException(
            'Не удалось определить шлюз по умолчанию.\n'
            'Проверьте сетевое подключение.');
      }

      // 2. Назначаем IP TUN адаптеру
      await Process.run('netsh', [
        'interface', 'ip', 'set', 'address',
        'name=$_tunName', 'static', _tunAddr, _tunMask,
      ], runInShell: false);

      await Future.delayed(const Duration(milliseconds: 500));

      // 3. Маршрут VPN-сервер → оригинальный шлюз (ОБЯЗАТЕЛЬНО, иначе петля)
      await Process.run('route', [
        'add', serverIp, 'mask', '255.255.255.255', _originalGateway!, 'metric', '1',
      ], runInShell: false);

      // 4. Весь остальной трафик → через TUN
      //    Добавляем два маршрута 0.0.0.0/1 и 128.0.0.0/1 вместо 0.0.0.0/0
      //    (они перекрывают дефолтный маршрут без его удаления)
      await Process.run('route', [
        'add', '0.0.0.0', 'mask', '128.0.0.0', _tunGateway, 'metric', '1',
      ], runInShell: false);
      await Process.run('route', [
        'add', '128.0.0.0', 'mask', '128.0.0.0', _tunGateway, 'metric', '1',
      ], runInShell: false);

      // 5. DNS через TUN (чтобы не было DNS утечек)
      await Process.run('netsh', [
        'interface', 'ip', 'set', 'dns',
        'name=$_tunName', 'static', '1.1.1.1',
      ], runInShell: false);

      _routesAdded = true;
      debugPrint('Routes added via $_tunName (GW: $_originalGateway)');
    } catch (e) {
      // Если маршруты не добавились — откатываем и кидаем ошибку
      await _removeRoutes();
      rethrow;
    }
  }

  Future<void> _removeRoutes() async {
    if (!_routesAdded) return;
    try {
      final srv = _vpnServerIp;
      final gw  = _originalGateway;

      if (srv != null && gw != null) {
        await Process.run('route', ['delete', srv, 'mask', '255.255.255.255'],
            runInShell: false);
      }
      await Process.run('route', ['delete', '0.0.0.0',   'mask', '128.0.0.0'],
          runInShell: false);
      await Process.run('route', ['delete', '128.0.0.0', 'mask', '128.0.0.0'],
          runInShell: false);

      _routesAdded     = false;
      _originalGateway = null;
      _vpnServerIp     = null;
      debugPrint('Routes removed');
    } catch (e) {
      debugPrint('_removeRoutes error (non-fatal): $e');
    }
  }

  Future<String?> _getDefaultGateway() async {
    // PowerShell: получаем активный шлюз по умолчанию
    final r = await Process.run(
      'powershell',
      ['-NoProfile', '-Command',
       '(Get-NetRoute -DestinationPrefix "0.0.0.0/0" | '
       'Sort-Object -Property RouteMetric | '
       'Select-Object -First 1).NextHop'],
      runInShell: false,
    );
    return r.stdout.toString().trim().isEmpty ? null : r.stdout.toString().trim();
  }

  // ═══════════════════════════════════════════════════════
  // AmneziaWG → полноценный WireGuard туннель
  // ═══════════════════════════════════════════════════════

  Future<void> _startAwg(VpnConnection conn) async {
    if (!File(_awgExePath).existsSync()) {
      throw VpnEngineException(
          'AmneziaWG не установлен.\n'
          'Перезапустите приложение — установка произойдёт автоматически.');
    }

    final confText = (conn.configJson != null &&
            conn.configJson!.trim().isNotEmpty)
        ? conn.configJson!
        : _buildAwgConfig(conn);

    final tunnelName = 'MilkyVPN${conn.id}';
    _awgTunnelName   = tunnelName;

    final appDir   = await getApplicationSupportDirectory();
    final confFile = File(p.join(appDir.path, '$tunnelName.conf'));
    await confFile.writeAsString(confText, flush: true);
    _tempConfigPath = confFile.path;

    // Убираем старый туннель (игнорируем ошибку)
    await _runHidden(_awgExePath, ['/uninstalltunnelservice', tunnelName]);
    await Future.delayed(const Duration(milliseconds: 800));

    // Устанавливаем туннель
    final r = await _runHidden(_awgExePath, ['/installtunnelservice', confFile.path]);
    if (r.exitCode != 0) {
      final err = '${r.stdout}\n${r.stderr}'.trim();
      throw VpnEngineException(
          'AWG: ошибка установки туннеля (код ${r.exitCode})\n$err'
          '${err.toLowerCase().contains('access') ? "\n⚠️ Запустите от имени Администратора!" : ""}');
    }

    await Future.delayed(const Duration(seconds: 3));

    final scName = 'AmneziaWGTunnel\$$tunnelName';
    final sc     = await Process.run('sc', ['query', scName], runInShell: true);
    final scOut  = sc.stdout.toString();

    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      throw VpnEngineException(
          'AWG туннель не запустился.\n'
          'Убедитесь что приложение запущено от Администратора.\n'
          'SC: $scOut');
    }

    _activeEngine = EngineType.awg;
    status.value  = VpnStatus.connected;
    _monitorAwg(tunnelName);
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

  String _buildXrayConfig(VpnConnection conn) {
    final outbound = <String, dynamic>{};

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

    return jsonEncode({
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
          // VPN-сервер — напрямую (иначе петля через TUN)
          {'type': 'field', 'ip': [conn.serverIp], 'outboundTag': 'direct'},
          // Локальные сети — напрямую
          {'type': 'field', 'ip': ['geoip:private'], 'outboundTag': 'direct'},
          // Всё остальное — через VPN
          {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'},
        ],
      },
    });
  }

  String _buildNaiveConfig(VpnConnection conn) {
    if (conn.configJson != null && conn.configJson!.trim().startsWith('{')) {
      try {
        final cfg = jsonDecode(conn.configJson!) as Map<String, dynamic>;
        cfg['listen'] = 'socks://127.0.0.1:${AppConstants.xraySocksPort}';
        cfg.remove('log');
        return jsonEncode(cfg);
      } catch (_) {}
    }
    final naivePort  = conn.connType == ConnectionType.cascade ? 8443 : 2096;
    final serverHost = conn.connType == ConnectionType.cascade
        ? 'ru.milkyims.com'
        : conn.serverIp;
    return jsonEncode({
      'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
      'proxy':  'https://admin:${conn.password ?? ""}@$serverHost:$naivePort',
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
      case 1:           return '\n⚠️ Проверьте UUID и publicKey сервера';
      default:          return '';
    }
  }

  // ═══════════════════════════════════════════════════════
  // Cleanup — гарантированный откат
  // ═══════════════════════════════════════════════════════

  Future<void> _forceCleanup() async {
    // 1. Убираем маршруты — ПЕРВЫМ ДЕЛОМ, пока адаптер ещё жив
    await _removeRoutes();

    // 2. Убиваем tun2socks
    if (_tunProcess != null) {
      try {
        _tunProcess!.kill();
        await _tunProcess!.exitCode
            .timeout(const Duration(seconds: 3))
            .catchError((_) => -1);
      } catch (_) {}
      _tunProcess = null;
    }

    // 3. Убиваем прокси (xray / naive)
    if (_proxyProcess != null) {
      try {
        _proxyProcess!.kill();
        await _proxyProcess!.exitCode
            .timeout(const Duration(seconds: 3))
            .catchError((_) => -1);
      } catch (_) {}
      _proxyProcess = null;
    }

    // 4. Удаляем AWG туннель
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgExePath).existsSync()) {
          await _runHidden(_awgExePath, ['/uninstalltunnelservice', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    }

    // 5. Удаляем временный конфиг
    if (_tempConfigPath != null) {
      try {
        final f = File(_tempConfigPath!);
        if (f.existsSync()) f.deleteSync();
      } catch (_) {}
      _tempConfigPath = null;
    }

    _activeEngine = null;
  }

  // ═══════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════

  Future<void> _assertAlive(Process proc, String name, StringBuffer buf) async {
    try {
      final code = await proc.exitCode.timeout(const Duration(milliseconds: 400));
      final log  = _tail(buf.toString(), 1000);
      throw VpnEngineException(
        '$name упал сразу после запуска (код $code)'
        '${log.isNotEmpty ? ":\n$log" : ""}',
      );
    } on TimeoutException {
      // Хорошо — процесс живёт
    }
  }

  Future<ProcessResult> _runHidden(String exe, List<String> args) =>
      Process.run(exe, args, runInShell: false);

  String _tail(String s, int maxLen) {
    s = s.trim();
    return s.length > maxLen ? '...' + s.substring(s.length - maxLen) : s;
  }

  Future<String> _engineDir() => EngineDownloader.instance.enginesDir;

  Future<String> _writeTempConfig(String name, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file   = File(p.join(appDir.path, name));
    await file.writeAsString(content, flush: true);
    return file.path;
  }
}

class VpnEngineException implements Exception {
  final String message;
  VpnEngineException(this.message);
  @override
  String toString() => 'VpnEngineException: $message';
}
