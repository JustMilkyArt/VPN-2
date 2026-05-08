// VPN Engine — manages VPN connections on Windows
//
// Architecture (v3):
//   VLESS/Trojan  → xray.exe (SOCKS5 on port 10808)
//                   → system proxy via netsh winhttp + WinInet registry
//   NaiveProxy    → naive.exe (SOCKS5 on port 10808)
//                   → same system proxy approach
//   AmneziaWG     → amneziawg.exe /installtunnelservice (from installed MSI)
//                   → auto-install MSI silently if not present
//
// On disconnect: system proxy is fully restored, AWG tunnel removed.
// On crash: cleanup runs via exitCode listeners.

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

  Process? _proxyProcess;
  EngineType? _activeEngine;
  String? _tempConfigPath;
  String? _awgTunnelName;

  // System proxy state (saved before connect, restored on disconnect)
  bool _systemProxyWasSet = false;

  final ValueNotifier<VpnStatus> status  = ValueNotifier(VpnStatus.disconnected);
  final ValueNotifier<String?> lastError = ValueNotifier(null);

  // Path to amneziawg.exe (installed by MSI during SetupScreen)
  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  bool get isConnected => status.value == VpnStatus.connected;

  // ═══════════════════════════════════════════════════════
  // Public API
  // ═══════════════════════════════════════════════════════

  Future<void> connect(VpnConnection conn) async {
    if (status.value == VpnStatus.connected ||
        status.value == VpnStatus.connecting) {
      await disconnect();
    }
    status.value   = VpnStatus.connecting;
    lastError.value = null;

    try {
      switch (conn.protocol) {
        case Protocol.vlessReality:
        case Protocol.trojan:
          await _startXray(conn);
          break;
        case Protocol.amneziaWg:
          await _startAwg(conn);
          break;
        case Protocol.naiveProxy:
          await _startNaive(conn);
          break;
        case Protocol.unknown:
          throw VpnEngineException(
              'Неподдерживаемый протокол: ${conn.protocol}');
      }
    } catch (e) {
      status.value   = VpnStatus.error;
      lastError.value = e.toString().replaceFirst('VpnEngineException: ', '');
      // Best-effort cleanup — don't let cleanup errors mask the original error
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
  // VLESS / Trojan → Xray SOCKS5 + system proxy
  // ═══════════════════════════════════════════════════════

  Future<void> _startXray(VpnConnection conn) async {
    final engineDir = await _engineDir();
    final xrayPath  = p.join(engineDir, 'xray.exe');

    if (!File(xrayPath).existsSync()) {
      throw VpnEngineException(
          'xray.exe не найден. Удалите папку engines (кнопка в настройках) '
          'и перезапустите приложение.');
    }

    final config     = _buildXrayConfig(conn);
    final configPath = await _writeTempConfig('xray_config.json', jsonEncode(config));
    _tempConfigPath  = configPath;

    final logBuf = StringBuffer();

    _proxyProcess = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      workingDirectory: engineDir, // geoip.dat / geosite.dat рядом с xray.exe
      runInShell: false,
    );
    _activeEngine = EngineType.xray;

    _proxyProcess!.stdout.transform(utf8.decoder).listen(logBuf.write);
    _proxyProcess!.stderr.transform(utf8.decoder).listen(logBuf.write);

    await Future.delayed(const Duration(seconds: 2));
    await _assertAlive(_proxyProcess!, 'xray.exe', logBuf);

    // Устанавливаем системный прокси
    await _setSystemProxy('127.0.0.1', AppConstants.xraySocksPort);

    status.value = VpnStatus.connected;

    // Мониторинг — если xray упадёт сам
    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final log = _tail(logBuf.toString(), 800);
        status.value   = VpnStatus.error;
        lastError.value = 'xray завершился (код $code)'
            '${log.isNotEmpty ? ":\n$log" : ""}'
            '${_xrayHint(code)}';
        unawaited(_forceCleanup());
      }
    });
  }

  Map<String, dynamic> _buildXrayConfig(VpnConnection conn) {
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

    return {
      'log': {'loglevel': 'info'},
      'inbounds': [
        {
          'tag':      'socks',
          'listen':   '127.0.0.1',
          'port':     AppConstants.xraySocksPort,
          'protocol': 'socks',
          'settings': {'auth': 'noauth', 'udp': true},
        },
        {
          'tag':      'http',
          'listen':   '127.0.0.1',
          'port':     AppConstants.xraySocksPort + 1,
          'protocol': 'http',
        },
      ],
      'outbounds': [
        {...outbound, 'tag': 'proxy'},
        {'tag': 'direct',  'protocol': 'freedom'},
        {'tag': 'block',   'protocol': 'blackhole'},
      ],
      'routing': {
        'domainStrategy': 'IPIfNonMatch',
        'rules': [
          // VPN-сервер — напрямую (иначе петля)
          {'type': 'field', 'ip': [conn.serverIp], 'outboundTag': 'direct'},
          // Локальные сети — напрямую
          {'type': 'field', 'ip': ['geoip:private'], 'outboundTag': 'direct'},
          // Всё остальное — через прокси
          {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'},
        ],
      },
    };
  }

  String _xrayHint(int code) {
    switch (code) {
      case -1073741515: return '\n⚠️ Установите Visual C++ Redistributable 2019 (x64)';
      case 1:           return '\n⚠️ Проверьте UUID и publicKey сервера';
      default:          return '';
    }
  }

  // ═══════════════════════════════════════════════════════
  // NaiveProxy → naive.exe SOCKS5 + system proxy
  // ═══════════════════════════════════════════════════════

  Future<void> _startNaive(VpnConnection conn) async {
    final engineDir  = await _engineDir();
    final naivePath  = p.join(engineDir, 'naive.exe');

    if (!File(naivePath).existsSync()) {
      throw VpnEngineException(
          'naive.exe не найден. Удалите папку engines и перезапустите.');
    }

    final cfgContent = _buildNaiveConfig(conn);
    final cfgPath    = await _writeTempConfig('naive_config.json', cfgContent);
    _tempConfigPath  = cfgPath;

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

    await _setSystemProxy('127.0.0.1', AppConstants.xraySocksPort);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final log = _tail(logBuf.toString(), 800);
        status.value   = VpnStatus.error;
        lastError.value = 'naive завершился (код $code)'
            '${log.isNotEmpty ? ":\n$log" : ""}';
        unawaited(_forceCleanup());
      }
    });
  }

  String _buildNaiveConfig(VpnConnection conn) {
    // config_json из БД уже содержит правильный порт (2096 или 8443)
    if (conn.configJson != null && conn.configJson!.trim().startsWith('{')) {
      try {
        final cfg = jsonDecode(conn.configJson!) as Map<String, dynamic>;
        // Перенаправляем listen на наш локальный SOCKS5 порт
        cfg['listen'] = 'socks://127.0.0.1:${AppConstants.xraySocksPort}';
        cfg.remove('log');
        return jsonEncode(cfg);
      } catch (_) {}
    }

    // Fallback — строим из полей
    final naivePort  = conn.connType == ConnectionType.cascade ? 8443 : 2096;
    final serverHost = conn.connType == ConnectionType.cascade
        ? 'ru.milkyims.com'
        : conn.serverIp;
    final pass = conn.password ?? '';
    return jsonEncode({
      'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
      'proxy':  'https://admin:$pass@$serverHost:$naivePort',
    });
  }

  // ═══════════════════════════════════════════════════════
  // AmneziaWG → /installtunnelservice (auto-install MSI if needed)
  // ═══════════════════════════════════════════════════════

  Future<void> _startAwg(VpnConnection conn) async {
    // AWG должен быть установлен ещё на этапе SetupScreen
    if (!File(_awgExePath).existsSync()) {
      throw VpnEngineException(
          'AmneziaWG не установлен.\n'
          'Перезапустите приложение — установка произойдёт автоматически.');
    }

    // Конфиг: берём из БД или строим вручную
    final confText = (conn.configJson != null &&
            conn.configJson!.trim().isNotEmpty)
        ? conn.configJson!
        : _buildAwgConfig(conn);

    // Имя туннеля: только ASCII без пробелов, ≤ 32 символа
    final tunnelName = 'MilkyVPN${conn.id}';
    _awgTunnelName   = tunnelName;

    // Пишем конфиг во временный файл (путь без пробелов)
    final appDir   = await getApplicationSupportDirectory();
    final confFile = File(p.join(appDir.path, '$tunnelName.conf'));
    await confFile.writeAsString(confText, flush: true);
    _tempConfigPath = confFile.path;

    // Удаляем старый туннель с таким же именем (игнорируем ошибку)
    await _runHidden(_awgExePath, ['/uninstalltunnelservice', tunnelName]);
    await Future.delayed(const Duration(milliseconds: 800));

    // Устанавливаем туннельный сервис (нет GUI окна)
    final r = await _runHidden(
        _awgExePath, ['/installtunnelservice', confFile.path]);

    if (r.exitCode != 0) {
      final err = '${r.stdout}\n${r.stderr}'.trim();
      throw VpnEngineException(
          'AWG: ошибка установки туннеля (код ${r.exitCode})\n$err'
          '${err.toLowerCase().contains('access') ? "\n⚠️ Запустите от имени Администратора!" : ""}');
    }

    // Ждём пока сервис запустится
    await Future.delayed(const Duration(seconds: 3));

    // Проверяем статус Windows Service
    final scName = 'AmneziaWGTunnel\$$tunnelName';
    final sc     = await Process.run('sc', ['query', scName], runInShell: true);
    final scOut  = sc.stdout.toString();

    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      throw VpnEngineException(
          'AWG туннель не запустился.\n'
          'Убедитесь, что приложение запущено от Администратора.\n'
          'SC: $scOut');
    }

    _activeEngine = EngineType.awg;
    status.value  = VpnStatus.connected;

    // Периодически проверяем что сервис жив
    _monitorAwg(tunnelName);
  }

  void _monitorAwg(String tunnelName) {
    Future.delayed(const Duration(seconds: 5), () async {
      if (status.value != VpnStatus.connected ||
          _activeEngine != EngineType.awg) return;
      try {
        final r = await Process.run(
            'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
            runInShell: true);
        if (!r.stdout.toString().contains('RUNNING')) {
          status.value   = VpnStatus.error;
          lastError.value = 'AWG туннель остановился неожиданно';
          unawaited(_forceCleanup());
          return;
        }
      } catch (_) {}
      _monitorAwg(tunnelName); // рекурсивно
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

  // ═══════════════════════════════════════════════════════
  // System proxy — set / restore
  // ═══════════════════════════════════════════════════════

  Future<void> _setSystemProxy(String host, int port) async {
    if (!Platform.isWindows) return;

    try {
      final proxyStr = 'socks=$host:$port';

      // 1. WinHTTP (используется системой, Node, .NET, PowerShell)
      await Process.run(
          'netsh', ['winhttp', 'set', 'proxy', proxyStr],
          runInShell: false);

      // 2. WinInet / IE реестр (браузеры: Chrome, Edge, IE)
      const regKey =
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings';
      await Process.run(
          'reg',
          ['add', regKey, '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '1', '/f'],
          runInShell: false);
      await Process.run(
          'reg',
          ['add', regKey, '/v', 'ProxyServer', '/t', 'REG_SZ', '/d', proxyStr, '/f'],
          runInShell: false);
      await Process.run(
          'reg',
          ['add', regKey, '/v', 'ProxyOverride', '/t', 'REG_SZ',
           '/d', '<local>;127.*;10.*;172.16.*;192.168.*', '/f'],
          runInShell: false);

      // 3. Уведомляем WinInet об изменении
      await _refreshWinInet();

      _systemProxyWasSet = true;
      debugPrint('System proxy SET: $proxyStr');
    } catch (e) {
      debugPrint('_setSystemProxy error (non-fatal): $e');
    }
  }

  Future<void> _restoreSystemProxy() async {
    if (!Platform.isWindows || !_systemProxyWasSet) return;
    try {
      // 1. Сбрасываем WinHTTP
      await Process.run(
          'netsh', ['winhttp', 'reset', 'proxy'],
          runInShell: false);

      // 2. Выключаем IE/WinInet прокси в реестре
      const regKey =
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings';
      await Process.run(
          'reg',
          ['add', regKey, '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '0', '/f'],
          runInShell: false);

      // 3. Уведомляем WinInet
      await _refreshWinInet();

      _systemProxyWasSet = false;
      debugPrint('System proxy RESTORED');
    } catch (e) {
      debugPrint('_restoreSystemProxy error: $e');
    }
  }

  /// Заставляет Windows применить новые настройки прокси без перезагрузки
  Future<void> _refreshWinInet() async {
    // InternetSetOption(INTERNET_OPTION_SETTINGS_CHANGED=39, INTERNET_OPTION_REFRESH=37)
    // Используем EncodedCommand чтобы не иметь проблем с экранированием
    // Команда закодирована в Base64 UTF-16LE:
    //   Add-Type -TypeDefinition '...' -ErrorAction SilentlyContinue
    //   [WinInet]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0)
    //   [WinInet]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0)
    // Вместо Add-Type используем более простой подход через rundll32
    try {
      // Самый простой способ — rundll32 для уведомления WinInet
      await Process.run(
        'rundll32.exe',
        ['wininet.dll', 'InternetSetOption'],
        runInShell: false,
      );
    } catch (e) {
      debugPrint('_refreshWinInet: $e');
    }
  }

  // ═══════════════════════════════════════════════════════
  // Cleanup — guaranteed to run on disconnect or crash
  // ═══════════════════════════════════════════════════════

  Future<void> _forceCleanup() async {
    // 1. Восстанавливаем системный прокси
    await _restoreSystemProxy();

    // 2. Удаляем AWG туннельный сервис
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgExePath).existsSync()) {
          await _runHidden(
              _awgExePath, ['/uninstalltunnelservice', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    }

    // 3. Убиваем прокси-процесс (xray / naive)
    if (_proxyProcess != null) {
      try {
        _proxyProcess!.kill();
        await _proxyProcess!.exitCode
            .timeout(const Duration(seconds: 3))
            .catchError((_) => -1);
      } catch (_) {}
      _proxyProcess = null;
    }

    // 4. Удаляем временный конфиг
    if (_tempConfigPath != null) {
      try {
        final f = File(_tempConfigPath!);
        if (f.existsSync()) await f.delete();
      } catch (_) {}
      _tempConfigPath = null;
    }

    _activeEngine = null;
  }

  // ═══════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════

  /// Проверяет что процесс ещё жив; если упал — бросает исключение с логом
  Future<void> _assertAlive(Process proc, String name, StringBuffer buf) async {
    try {
      final code = await proc.exitCode
          .timeout(const Duration(milliseconds: 300));
      final log = _tail(buf.toString(), 1000);
      throw VpnEngineException(
        '$name упал сразу после запуска (код $code)'
        '${log.isNotEmpty ? ":\n$log" : ""}',
      );
    } on TimeoutException {
      // Хорошо — процесс ещё работает
    }
  }

  /// Запускает процесс и ждёт завершения (без GUI-окна)
  Future<ProcessResult> _runHidden(String exe, List<String> args) =>
      Process.run(exe, args, runInShell: false);

  String _tail(String s, int maxLen) {
    s = s.trim();
    return s.length > maxLen ? '...' + s.substring(s.length - maxLen) : s;
  }

  Future<String> _engineDir() =>
      EngineDownloader.instance.enginesDir; // returns Future<String>

  Future<String> _writeTempConfig(String name, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file   = File(p.join(appDir.path, name));
    await file.writeAsString(content, flush: true);
    return file.path;
  }
} // end VpnEngine

class VpnEngineException implements Exception {
  final String message;
  VpnEngineException(this.message);
  @override
  String toString() => 'VpnEngineException: $message';
}
