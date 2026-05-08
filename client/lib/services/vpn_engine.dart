// VPN Engine — manages VPN subprocesses on Windows
//
// Architecture:
//   VLESS/Trojan  → xray.exe (SOCKS5 on 10808) + tun2socks.exe (TUN adapter)
//   NaiveProxy    → naive.exe (SOCKS5 on 10808) + tun2socks.exe (TUN adapter)
//   AmneziaWG     → amneziawg.exe /installtunnelservice (Windows tunnel service, no GUI)
//
// tun2socks creates a virtual TUN network adapter and routes ALL OS traffic
// through the local SOCKS5 proxy — works for every app, browser, game, etc.
//
// IMPORTANT: The app must be run as Administrator (UAC elevated).
//   - tun2socks.exe needs WinTUN driver (bundled wintun.dll) + admin rights.
//   - amneziawg.exe /installtunnelservice also needs admin rights.

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

  Process? _proxyProcess;     // xray.exe or naive.exe
  Process? _tun2socksProcess; // tun2socks.exe
  EngineType? _activeEngine;
  String? _tempConfigPath;
  String? _awgTunnelName;
  String? _originalGateway;
  String? _vpnServerIp;

  // TUN adapter settings
  static const _tunName = 'MilkyVPN-TUN';
  static const _tunAddr = '198.18.0.1';  // RFC 5737 test range — won't clash
  static const _tunGw   = '198.18.0.2';
  static const _tunMask = '255.255.255.0';

  // AWG client path
  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  final ValueNotifier<VpnStatus> status   = ValueNotifier(VpnStatus.disconnected);
  final ValueNotifier<String?> lastError  = ValueNotifier(null);

  bool get isConnected => status.value == VpnStatus.connected;

  // ═══════════════════════════════════════════════════════
  // Public: connect / disconnect
  // ═══════════════════════════════════════════════════════

  Future<void> connect(VpnConnection conn) async {
    if (status.value == VpnStatus.connected ||
        status.value == VpnStatus.connecting) {
      await disconnect();
    }
    status.value  = VpnStatus.connecting;
    lastError.value = null;

    try {
      final engineDir = await _engineDir();

      switch (conn.protocol) {
        case Protocol.vlessReality:
        case Protocol.trojan:
          await _startXrayWithTun(conn, engineDir);
          break;
        case Protocol.amneziaWg:
          await _startAwg(conn, engineDir);
          break;
        case Protocol.naiveProxy:
          await _startNaiveWithTun(conn, engineDir);
          break;
        case Protocol.unknown:
          throw VpnEngineException('Unsupported protocol: ${conn.protocol}');
      }
    } catch (e) {
      status.value   = VpnStatus.error;
      lastError.value = e.toString().replaceFirst('VpnEngineException: ', '');
      await _killAllProcesses();
      rethrow;
    }
  }

  Future<void> disconnect() async {
    if (status.value == VpnStatus.disconnected) return;
    status.value = VpnStatus.disconnecting;
    await _killAllProcesses();
    await _cleanupTempConfig();
    status.value = VpnStatus.disconnected;
  }

  // ═══════════════════════════════════════════════════════
  // VLESS / Trojan → Xray + tun2socks
  // ═══════════════════════════════════════════════════════

  Future<void> _startXrayWithTun(VpnConnection conn, String engineDir) async {
    final xrayPath = p.join(engineDir, 'xray.exe');
    if (!File(xrayPath).existsSync()) {
      throw VpnEngineException('xray.exe не найден. Удалите папку engines и перезапустите приложение.');
    }

    final config     = _buildXrayClientConfig(conn);
    final configPath = await _writeTempConfig('xray_config.json', jsonEncode(config));
    _tempConfigPath  = configPath;

    final stderrBuf = StringBuffer();

    _proxyProcess = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      workingDirectory: engineDir, // xray ищет geoip.dat / geosite.dat рядом с собой
      runInShell: false,
    );
    _activeEngine = EngineType.xray;
    _proxyProcess!.stderr.transform(utf8.decoder).listen((s) => stderrBuf.write(s));
    _proxyProcess!.stdout.transform(utf8.decoder).listen((s) => stderrBuf.write(s));

    // Ждём 2с чтобы xray успел стартовать
    await Future.delayed(const Duration(seconds: 2));
    await _checkProcessAlive(_proxyProcess!, 'xray.exe', stderrBuf);

    _vpnServerIp = conn.serverIp;
    await _startTun2socks(engineDir);

    status.value = VpnStatus.connected;

    // Мониторим xray
    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final tail = _tail(stderrBuf.toString(), 400);
        status.value   = VpnStatus.error;
        lastError.value = 'xray завершился (код $code)${tail.isNotEmpty ? ":\n$tail" : ""}';
        _killAllProcesses();
      }
    });
  }

  Map<String, dynamic> _buildXrayClientConfig(VpnConnection conn) {
    final outbound = <String, dynamic>{};

    if (conn.protocol == Protocol.vlessReality) {
      outbound['protocol'] = 'vless';
      outbound['settings'] = {
        'vnext': [{
          'address': conn.serverIp,
          'port': conn.port,
          'users': [{
            'id': conn.uuid ?? '',
            'flow': 'xtls-rprx-vision',
            'encryption': 'none',
          }],
        }]
      };
      outbound['streamSettings'] = {
        'network': 'tcp',
        'security': 'reality',
        'realitySettings': {
          'fingerprint': 'chrome',
          'serverName': conn.realityServerName ?? 'www.microsoft.com',
          'publicKey': conn.realityPublicKey ?? '',
          'shortId': conn.realityShortId ?? '',
          'spiderX': '/',
        },
      };
    } else if (conn.protocol == Protocol.trojan) {
      outbound['protocol'] = 'trojan';
      outbound['settings'] = {
        'servers': [{
          'address': conn.serverIp,
          'port': conn.port,
          'password': conn.password ?? '',
        }]
      };
      outbound['streamSettings'] = {
        'network': 'tcp',
        'security': 'tls',
        'tlsSettings': {'serverName': conn.serverIp},
      };
    }

    return {
      'log': {'loglevel': 'warning'},
      'inbounds': [{
        'tag': 'socks-in',
        'listen': '127.0.0.1',
        'port': AppConstants.xraySocksPort,
        'protocol': 'socks',
        'settings': {'auth': 'noauth', 'udp': true},
      }],
      'outbounds': [
        {...outbound, 'tag': 'proxy'},
        {'tag': 'direct', 'protocol': 'freedom'},
      ],
      'routing': {
        'domainStrategy': 'IPIfNonMatch',
        'rules': [
          // VPN сервер идёт напрямую (избегаем петли)
          {'type': 'field', 'ip': [conn.serverIp], 'outboundTag': 'direct'},
          // Локальные сети — напрямую
          {'type': 'field', 'ip': ['geoip:private'], 'outboundTag': 'direct'},
          // Всё остальное — через прокси
          {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'},
        ],
      },
    };
  }

  // ═══════════════════════════════════════════════════════
  // NaiveProxy → naive.exe + tun2socks
  // ═══════════════════════════════════════════════════════

  Future<void> _startNaiveWithTun(VpnConnection conn, String engineDir) async {
    final naivePath = p.join(engineDir, 'naive.exe');
    if (!File(naivePath).existsSync()) {
      throw VpnEngineException('naive.exe не найден. Удалите папку engines и перезапустите приложение.');
    }

    // Строим конфиг: используем config_json из бэкенда, но правим listen и порт
    // ВАЖНО: Caddy-naive слушает на порту 2096 (не 443)
    final configContent = _buildNaiveConfig(conn);
    final configPath    = await _writeTempConfig('naive_config.json', configContent);
    _tempConfigPath     = configPath;

    final outputBuf = StringBuffer();

    _proxyProcess = await Process.start(
      naivePath,
      ['--config=$configPath'],
      runInShell: false,
    );
    _activeEngine = EngineType.naive;
    _proxyProcess!.stderr.transform(utf8.decoder).listen((s) => outputBuf.write(s));
    _proxyProcess!.stdout.transform(utf8.decoder).listen((s) => outputBuf.write(s));

    await Future.delayed(const Duration(milliseconds: 1500));
    await _checkProcessAlive(_proxyProcess!, 'naive.exe', outputBuf);

    _vpnServerIp = conn.serverIp;
    await _startTun2socks(engineDir);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final tail = _tail(outputBuf.toString(), 400);
        status.value   = VpnStatus.error;
        lastError.value = 'naive завершился (код $code)${tail.isNotEmpty ? ":\n$tail" : ""}';
        _killAllProcesses();
      }
    });
  }

  String _buildNaiveConfig(VpnConnection conn) {
    // Caddy-naive на обоих серверах слушает на порту 2096 (не 443!)
    // config_json из бэкенда может содержать неправильный порт — исправляем
    const naivePort = 2096;

    if (conn.configJson != null && conn.configJson!.trim().startsWith('{')) {
      try {
        final cfg = jsonDecode(conn.configJson!) as Map<String, dynamic>;

        // Исправляем listen: используем порт 10808 как SOCKS5
        cfg['listen'] = 'socks://127.0.0.1:${AppConstants.xraySocksPort}';

        // Исправляем proxy URL: заменяем порт на 2096
        if (cfg.containsKey('proxy')) {
          final proxyUrl = cfg['proxy'] as String;
          // Заменяем порт в конце URL (после последнего :)
          final uri = Uri.tryParse(proxyUrl);
          if (uri != null && uri.port != naivePort) {
            cfg['proxy'] = Uri(
              scheme: uri.scheme,
              userInfo: uri.userInfo,
              host: uri.host,
              port: naivePort,
              path: uri.path,
            ).toString();
          }
        }

        cfg.remove('log'); // убираем лог-файл
        return jsonEncode(cfg);
      } catch (_) {
        // Если парсинг упал — строим сами
      }
    }

    // Строим конфиг вручную
    final user     = conn.password != null ? 'admin:${conn.password}' : 'admin';
    final serverIp = conn.serverIp;
    return jsonEncode({
      'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
      'proxy': 'https://$user@$serverIp:$naivePort',
    });
  }

  // ═══════════════════════════════════════════════════════
  // tun2socks — виртуальный TUN адаптер
  // ═══════════════════════════════════════════════════════

  Future<void> _startTun2socks(String engineDir) async {
    final tun2socksPath = p.join(engineDir, 'tun2socks.exe');
    if (!File(tun2socksPath).existsSync()) {
      throw VpnEngineException('tun2socks.exe не найден. Удалите папку engines и перезапустите приложение.');
    }

    // wintun.dll должна быть в той же папке что и tun2socks.exe (engineDir)
    // Она туда уже кладётся при скачивании Xray zip
    final wintunPath = p.join(engineDir, 'wintun.dll');
    if (!File(wintunPath).existsSync()) {
      throw VpnEngineException('wintun.dll не найден. Удалите папку engines и перезапустите приложение.');
    }

    final t2sBuf = StringBuffer();

    // tun2socks на Windows использует WinTUN драйвер
    // Формат device: tun://ADAPTER_NAME
    _tun2socksProcess = await Process.start(
      tun2socksPath,
      [
        '-device',   'tun://$_tunName',
        '-proxy',    'socks5://127.0.0.1:${AppConstants.xraySocksPort}',
        '-loglevel', 'warning',
      ],
      workingDirectory: engineDir, // wintun.dll должна быть рядом
      runInShell: false,
    );

    _tun2socksProcess!.stderr.transform(utf8.decoder).listen((s) => t2sBuf.write(s));
    _tun2socksProcess!.stdout.transform(utf8.decoder).listen((s) => t2sBuf.write(s));

    // Даём 3 секунды чтобы TUN адаптер поднялся
    await Future.delayed(const Duration(seconds: 3));
    await _checkProcessAlive(_tun2socksProcess!, 'tun2socks.exe', t2sBuf);

    // Настраиваем маршрутизацию
    await _setupRoutes(add: true);

    // Мониторим tun2socks
    _tun2socksProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final tail = _tail(t2sBuf.toString(), 300);
        status.value   = VpnStatus.error;
        lastError.value = 'tun2socks завершился (код $code)${tail.isNotEmpty ? ":\n$tail" : ""}';
        _killAllProcesses();
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  // AmneziaWG — Windows Tunnel Service (без GUI)
  // ═══════════════════════════════════════════════════════

  Future<void> _startAwg(VpnConnection conn, String engineDir) async {
    if (!File(_awgExePath).existsSync()) {
      throw VpnEngineException(
        'AmneziaWG не установлен.\n'
        'Установите клиент (без регистрации, просто нажмите Next):\n'
        'https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi\n'
        'После установки перезапустите MilkyVPN.',
      );
    }

    // Берём конфиг из бэкенда (config_json уже содержит правильный AWG .conf)
    final confText   = conn.configJson ?? _buildAwgConfig(conn);
    // Имя туннеля — только буквы/цифры, без пробелов и спецсимволов
    final tunnelName = 'MilkyVPN${conn.id}';
    _awgTunnelName   = tunnelName;

    // Пишем конфиг в AppData (без пробелов в пути)
    final appDir   = await getApplicationSupportDirectory();
    final confFile = File(p.join(appDir.path, '$tunnelName.conf'));
    await confFile.writeAsString(confText, flush: true);
    _tempConfigPath = confFile.path;

    // Удаляем старый туннель с таким же именем (игнорируем ошибки)
    await _runHidden(_awgExePath, ['/uninstalltunnelservice', tunnelName]);
    await Future.delayed(const Duration(milliseconds: 1000));

    // Устанавливаем туннельный сервис — без GUI окна
    final result = await _runHidden(
      _awgExePath,
      ['/installtunnelservice', confFile.path],
    );

    if (result.exitCode != 0) {
      final err = '${result.stdout}\n${result.stderr}'.trim();
      final hint = err.contains('access') || err.contains('Access')
          ? '\n⚠️ Запустите MilkyVPN от имени Администратора!'
          : '';
      throw VpnEngineException('AWG: ошибка установки туннеля (код ${result.exitCode})$hint\n$err');
    }

    // Ждём старта сервиса
    await Future.delayed(const Duration(seconds: 3));

    // Проверяем что сервис запущен
    final sc = await Process.run(
      'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
      runInShell: true,
    );
    final scOut = sc.stdout.toString();
    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      throw VpnEngineException(
        'AWG туннель не запустился.\n'
        'Попробуйте:\n'
        '1. Запустите MilkyVPN от имени Администратора\n'
        '2. Убедитесь что AmneziaWG установлен корректно\n'
        'SC: $scOut',
      );
    }

    _activeEngine = EngineType.awg;
    status.value  = VpnStatus.connected;
    _monitorAwgTunnel(tunnelName);
  }

  void _monitorAwgTunnel(String tunnelName) {
    Future.delayed(const Duration(seconds: 5), () async {
      if (status.value != VpnStatus.connected || _activeEngine != EngineType.awg) return;
      try {
        final r = await Process.run(
          'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
          runInShell: true,
        );
        if (!r.stdout.toString().contains('RUNNING') &&
            status.value == VpnStatus.connected) {
          status.value   = VpnStatus.error;
          lastError.value = 'AWG туннель остановился неожиданно';
          _killAllProcesses();
          return;
        }
      } catch (_) {}
      _monitorAwgTunnel(tunnelName); // рекурсивный мониторинг
    });
  }

  String _buildAwgConfig(VpnConnection conn) {
    // Резервный конфиг если config_json недоступен
    final jc   = conn.awgJunkPacketCount    ?? 4;
    final jmin = conn.awgJunkPacketMinSize  ?? 40;
    final jmax = conn.awgJunkPacketMaxSize  ?? 70;
    return '[Interface]\n'
        'PrivateKey = ${conn.wgClientPrivateKey ?? ""}\n'
        'Address = ${conn.wgClientIp ?? "10.8.0.2"}/32\n'
        'DNS = 1.1.1.1, 8.8.8.8\n'
        'MTU = 1420\n'
        'Jc = $jc\nJmin = $jmin\nJmax = $jmax\n'
        'S1 = 50\nS2 = 100\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n\n'
        '[Peer]\n'
        'PublicKey = ${conn.wgPublicKey ?? ""}\n'
        'PresharedKey = ${conn.wgPresharedKey ?? ""}\n'
        'Endpoint = ${conn.serverIp}:${conn.port}\n'
        'AllowedIPs = 0.0.0.0/0, ::/0\n'
        'PersistentKeepalive = 25\n';
  }

  // ═══════════════════════════════════════════════════════
  // Маршрутизация для tun2socks
  // ═══════════════════════════════════════════════════════

  Future<void> _setupRoutes({required bool add}) async {
    if (!Platform.isWindows) return;
    try {
      if (add) {
        // 1. Запоминаем текущий default gateway
        final gwResult = await Process.run(
          'powershell', ['-NoProfile', '-Command',
            '(Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric | Select-Object -First 1).NextHop'
          ],
        );
        _originalGateway = gwResult.stdout.toString().trim();
        debugPrint('Original gateway: $_originalGateway');

        // 2. Ждём появления TUN адаптера
        await Future.delayed(const Duration(milliseconds: 500));
        final idxResult = await Process.run(
          'powershell', ['-NoProfile', '-Command',
            r'(Get-NetAdapter | Where-Object {$_.Name -like "*' + _tunName + r'*"} | Select-Object -First 1).ifIndex'
          ],
        );
        final tunIdx = idxResult.stdout.toString().trim();
        debugPrint('TUN index: $tunIdx');

        if (tunIdx.isNotEmpty &&
            _originalGateway != null &&
            _originalGateway!.isNotEmpty &&
            _originalGateway != '0.0.0.0') {

          // 3. Маршрут для VPN сервера через реальный gateway (чтобы не было петли)
          if (_vpnServerIp != null) {
            await Process.run('route', [
              'add', _vpnServerIp!, 'mask', '255.255.255.255', _originalGateway!,
            ], runInShell: true);
            debugPrint('Added VPN server route: $_vpnServerIp via $_originalGateway');
          }

          // 4. Назначаем IP TUN адаптеру
          await Process.run('netsh', [
            'interface', 'ip', 'set', 'address',
            'name=$_tunName', 'static', _tunAddr, _tunMask, _tunGw,
          ], runInShell: true);

          // 5. Маршрут по умолчанию через TUN (метрика 1 — выше приоритет)
          await Process.run('route', [
            'add', '0.0.0.0', 'mask', '0.0.0.0', _tunGw, 'metric', '1',
          ], runInShell: true);
          debugPrint('Added default route via TUN $_tunGw');
        } else {
          debugPrint('WARNING: Could not get TUN index or gateway. Routes not set.');
        }
      } else {
        // Удаляем маршруты при отключении
        await Process.run('route', ['delete', '0.0.0.0', 'mask', '0.0.0.0', _tunGw],
            runInShell: true);
        if (_vpnServerIp != null && _originalGateway != null) {
          await Process.run('route', ['delete', _vpnServerIp!, 'mask', '255.255.255.255'],
              runInShell: true);
        }
        _originalGateway = null;
        _vpnServerIp     = null;
      }
    } catch (e) {
      debugPrint('Route setup error: $e');
    }
  }

  // ═══════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════

  /// Запускает процесс без GUI окна (CREATE_NO_WINDOW) и ждёт завершения.
  /// Используется для AWG чтобы не показывать окно консоли пользователю.
  Future<ProcessResult> _runHidden(String exe, List<String> args) async {
    // На Windows Process.run по умолчанию не показывает окно
    // Для гарантии используем runInShell: false
    return Process.run(exe, args, runInShell: false);
  }

  Future<void> _checkProcessAlive(
      Process proc, String name, StringBuffer buf) async {
    try {
      final code = await proc.exitCode
          .timeout(const Duration(milliseconds: 100));
      final err = _tail(buf.toString(), 600);
      throw VpnEngineException(
        '$name упал сразу после запуска (код $code)'
        '${err.isNotEmpty ? ":\n$err" : ""}'
        '${code == -1073741515 ? "\n⚠️ Возможно отсутствует Visual C++ Redistributable" : ""}',
      );
    } on TimeoutException {
      // Всё хорошо — процесс ещё работает
    }
  }

  String _tail(String s, int maxLen) {
    s = s.trim();
    return s.length > maxLen ? '...' + s.substring(s.length - maxLen) : s;
  }

  Future<String> _engineDir() async {
    return await EngineDownloader.instance.enginesDir;
  }

  Future<String> _writeTempConfig(String filename, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file   = File(p.join(appDir.path, filename));
    await file.writeAsString(content, flush: true);
    return file.path;
  }

  Future<void> _killAllProcesses() async {
    // 1. Удаляем AWG туннельный сервис
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgExePath).existsSync()) {
          await _runHidden(_awgExePath, ['/uninstalltunnelservice', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    }

    // 2. Убираем маршруты (для VLESS/Naive)
    if (_activeEngine != EngineType.awg) {
      await _setupRoutes(add: false);
    }

    // 3. Убиваем tun2socks
    if (_tun2socksProcess != null) {
      try {
        _tun2socksProcess!.kill();
        await _tun2socksProcess!.exitCode
            .timeout(const Duration(seconds: 2))
            .catchError((_) => -1);
      } catch (_) {}
      _tun2socksProcess = null;
    }

    // 4. Убиваем proxy процесс (xray / naive)
    if (_proxyProcess != null) {
      try {
        _proxyProcess!.kill();
        await _proxyProcess!.exitCode
            .timeout(const Duration(seconds: 2))
            .catchError((_) => -1);
      } catch (_) {}
      _proxyProcess = null;
    }

    _activeEngine = null;
  }

  Future<void> _cleanupTempConfig() async {
    if (_tempConfigPath != null) {
      try {
        final f = File(_tempConfigPath!);
        if (f.existsSync()) await f.delete();
      } catch (_) {}
      _tempConfigPath = null;
    }
  }
}

class VpnEngineException implements Exception {
  final String message;
  VpnEngineException(this.message);
  @override
  String toString() => 'VpnEngineException: $message';
}
