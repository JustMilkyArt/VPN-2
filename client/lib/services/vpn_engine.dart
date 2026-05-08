// VPN Engine — manages xray.exe / amneziawg tunnel service / naive.exe subprocesses

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

  Process? _process;
  EngineType? _activeEngine;
  String? _tempConfigPath;
  String? _awgTunnelName;

  final ValueNotifier<VpnStatus> status =
      ValueNotifier(VpnStatus.disconnected);
  final ValueNotifier<String?> lastError = ValueNotifier(null);

  bool get isConnected => status.value == VpnStatus.connected;

  // ── Public: connect ───────────────────────────────────────────────────────

  Future<void> connect(VpnConnection conn) async {
    if (status.value == VpnStatus.connected ||
        status.value == VpnStatus.connecting) {
      await disconnect();
    }

    status.value = VpnStatus.connecting;
    lastError.value = null;

    try {
      final engineDir = await _engineDir();

      switch (conn.protocol) {
        case Protocol.vlessReality:
        case Protocol.trojan:
          await _startXray(conn, engineDir);
          break;
        case Protocol.amneziaWg:
          await _startAwg(conn, engineDir);
          break;
        case Protocol.naiveProxy:
          await _startNaive(conn, engineDir);
          break;
        case Protocol.unknown:
          throw VpnEngineException('Unsupported protocol: ${conn.protocol}');
      }
    } catch (e) {
      status.value = VpnStatus.error;
      lastError.value = e.toString().replaceFirst('VpnEngineException: ', '');
      rethrow;
    }
  }

  // ── Public: disconnect ────────────────────────────────────────────────────

  Future<void> disconnect() async {
    if (status.value == VpnStatus.disconnected) return;
    status.value = VpnStatus.disconnecting;
    await _stopCurrentProcess();
    await _cleanupTempConfig();
    status.value = VpnStatus.disconnected;
  }

  // ── XRAY (VLESS+Reality, Trojan) ──────────────────────────────────────────

  Future<void> _startXray(VpnConnection conn, String engineDir) async {
    final xrayPath = p.join(engineDir, AppConstants.xrayExe);
    if (!File(xrayPath).existsSync()) {
      throw VpnEngineException('xray.exe not found. Run setup again.');
    }

    // Pass engineDir so xray finds geoip.dat / geosite.dat
    final config = _buildXrayClientConfig(conn, engineDir);
    final configPath = await _writeTempConfig(
        AppConstants.xrayConfigFile, jsonEncode(config));
    _tempConfigPath = configPath;

    // Collect stderr from the very start for diagnostics
    final stderrBuffer = StringBuffer();

    _process = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      runInShell: false,
      // Run in the engineDir so xray finds geo files relative to itself
      workingDirectory: engineDir,
    );
    _activeEngine = EngineType.xray;

    _process!.stderr.transform(utf8.decoder).listen((s) => stderrBuffer.write(s));
    _process!.stdout.transform(utf8.decoder).listen((s) => stderrBuffer.write(s));

    // Wait 1.5s and see if process is still alive
    await Future.delayed(const Duration(milliseconds: 1500));

    bool crashed = false;
    String crashErr = '';

    try {
      final code = await _process!.exitCode
          .timeout(const Duration(milliseconds: 50));
      // If we got here — process already exited (crashed)
      crashed = true;
      crashErr = stderrBuffer.toString().trim();
      throw VpnEngineException(
          'xray.exe crashed (exit $code)${crashErr.isNotEmpty ? ':\n$crashErr' : ''}');
    } on TimeoutException {
      // Good — still running
    }

    if (crashed) return;

    await _setSystemProxy(enabled: true);
    status.value = VpnStatus.connected;

    // Monitor background exit
    _process!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final err = stderrBuffer.toString().trim();
        final tail = err.length > 300 ? err.substring(err.length - 300) : err;
        status.value = VpnStatus.error;
        lastError.value =
            'VPN process exited (code $code)${tail.isNotEmpty ? ':\n$tail' : ''}';
      }
    });
  }

  /// Build xray client config.
  /// [engineDir] is used to set assetLocation so xray finds geoip/geosite.
  Map<String, dynamic> _buildXrayClientConfig(
      VpnConnection conn, String engineDir) {
    final outbound = <String, dynamic>{};

    if (conn.protocol == Protocol.vlessReality) {
      outbound['protocol'] = 'vless';
      outbound['settings'] = {
        'vnext': [
          {
            'address': conn.serverIp,
            'port': conn.port,
            'users': [
              {
                'id': conn.uuid ?? '',
                'flow': 'xtls-rprx-vision',
                'encryption': 'none',
              }
            ],
          }
        ]
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
        'servers': [
          {
            'address': conn.serverIp,
            'port': conn.port,
            'password': conn.password ?? '',
          }
        ]
      };
      outbound['streamSettings'] = {
        'network': 'tcp',
        'security': 'tls',
        'tlsSettings': {'serverName': conn.serverIp},
      };
    }

    return {
      // Tell xray where to look for geoip.dat / geosite.dat
      'log': {'loglevel': 'warning'},
      'inbounds': [
        {
          'tag': 'socks-in',
          'listen': '127.0.0.1',
          'port': AppConstants.xraySocksPort,
          'protocol': 'socks',
          'settings': {'auth': 'noauth', 'udp': true},
        },
        {
          'tag': 'http-in',
          'listen': '127.0.0.1',
          'port': AppConstants.xraySocksPort + 1,
          'protocol': 'http',
        },
      ],
      'outbounds': [
        {...outbound, 'tag': 'proxy'},
        {'tag': 'direct', 'protocol': 'freedom'},
        {'tag': 'block', 'protocol': 'blackhole'},
      ],
      'routing': {
        'domainStrategy': 'IPIfNonMatch',
        'rules': [
          // Private IPs go direct (LAN, loopback)
          {
            'type': 'field',
            'ip': ['geoip:private'],
            'outboundTag': 'direct',
          },
          // Everything else through proxy
          {
            'type': 'field',
            'network': 'tcp,udp',
            'outboundTag': 'proxy',
          },
        ],
      },
    };
  }

  // ── AWG (AmneziaWG) — Windows Tunnel Service ──────────────────────────────
  //
  // amneziawg-windows-client installs amneziawg.exe which supports:
  //   amneziawg.exe /installtunnel <config.conf>
  //   amneziawg.exe /removetunnel  <tunnel_name>
  //
  // Default install path: C:\Program Files\AmneziaWG\amneziawg.exe

  static const _awgInstallPath =
      r'C:\Program Files\AmneziaWG\amneziawg.exe';

  Future<void> _startAwg(VpnConnection conn, String engineDir) async {
    final confText = conn.configJson ?? _buildAwgConfig(conn);
    final tunnelName = 'MilkyVPN_${conn.id}';
    _awgTunnelName = tunnelName;

    // Write config to app support dir (no spaces in path)
    final appDir = await getApplicationSupportDirectory();
    final confFile = File(p.join(appDir.path, '$tunnelName.conf'));
    await confFile.writeAsString(confText);
    _tempConfigPath = confFile.path;

    if (File(_awgInstallPath).existsSync()) {
      await _startAwgViaTunnel(confFile.path, tunnelName);
    } else {
      throw VpnEngineException(
          'AmneziaWG не установлен на компьютере.\n'
          'Скачайте и установите: https://github.com/amnezia-vpn/amneziawg-windows-client/releases\n'
          'После установки перезапустите MilkyVPN.');
    }
  }

  Future<void> _startAwgViaTunnel(String confPath, String tunnelName) async {
    // Remove stale tunnel if exists
    try {
      await Process.run(_awgInstallPath, ['/removetunnel', tunnelName]);
      await Future.delayed(const Duration(milliseconds: 500));
    } catch (_) {}

    // Install tunnel as Windows service
    final result = await Process.run(
      _awgInstallPath,
      ['/installtunnel', confPath],
    );

    if (result.exitCode != 0) {
      final err = '${result.stdout}\n${result.stderr}'.trim();
      throw VpnEngineException(
          'AWG tunnel install failed (exit ${result.exitCode}): $err');
    }

    // Wait for service to start
    await Future.delayed(const Duration(seconds: 2));

    // Verify running
    final sc = await Process.run(
      'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
      runInShell: true,
    );
    final scOut = sc.stdout.toString();
    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      throw VpnEngineException('AWG tunnel не запустился: $scOut');
    }

    _activeEngine = EngineType.awg;
    status.value = VpnStatus.connected;
    _monitorAwgTunnel(tunnelName);
  }

  void _monitorAwgTunnel(String tunnelName) {
    Future.delayed(const Duration(seconds: 5), () async {
      if (status.value != VpnStatus.connected ||
          _activeEngine != EngineType.awg) return;
      try {
        final r = await Process.run(
          'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
          runInShell: true,
        );
        if (!r.stdout.toString().contains('RUNNING') &&
            status.value == VpnStatus.connected) {
          status.value = VpnStatus.error;
          lastError.value = 'AWG туннель остановился неожиданно';
          return;
        }
      } catch (_) {}
      _monitorAwgTunnel(tunnelName);
    });
  }

  String _buildAwgConfig(VpnConnection conn) {
    final s1 = 15 + (conn.id * 7) % 136;
    final s2 = 15 + (conn.id * 13) % 136;
    return '[Interface]\n'
        'PrivateKey = ${conn.wgClientPrivateKey ?? ''}\n'
        'Address = ${conn.wgClientIp ?? '10.8.0.2'}/32\n'
        'DNS = 1.1.1.1, 8.8.8.8\n'
        'MTU = 1420\n'
        'Jc = ${conn.awgJunkPacketCount ?? 4}\n'
        'Jmin = ${conn.awgJunkPacketMinSize ?? 40}\n'
        'Jmax = ${conn.awgJunkPacketMaxSize ?? 70}\n'
        'S1 = $s1\n'
        'S2 = $s2\n'
        'H1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n\n'
        '[Peer]\n'
        'PublicKey = ${conn.wgPublicKey ?? ''}\n'
        'PresharedKey = ${conn.wgPresharedKey ?? ''}\n'
        'Endpoint = ${conn.serverIp}:${conn.port}\n'
        'AllowedIPs = 0.0.0.0/0, ::/0\n'
        'PersistentKeepalive = 25\n';
  }

  // ── NaiveProxy ────────────────────────────────────────────────────────────
  //
  // naive.exe runs as local SOCKS5 proxy on port xraySocksPort.
  // config_json from backend already has the correct proxy URL with credentials.
  // System proxy is set via WinINet registry + winhttp for broad app coverage.

  Future<void> _startNaive(VpnConnection conn, String engineDir) async {
    final naivePath = p.join(engineDir, AppConstants.naiveExe);
    if (!File(naivePath).existsSync()) {
      throw VpnEngineException('naive.exe not found. Run setup again.');
    }

    // Use config_json from backend (already has correct proxy URL + credentials).
    // Only override the listen port to match our constant.
    String configContent;
    if (conn.configJson != null && conn.configJson!.trim().startsWith('{')) {
      try {
        final cfg = jsonDecode(conn.configJson!) as Map<String, dynamic>;
        cfg['listen'] = 'socks://127.0.0.1:${AppConstants.xraySocksPort}';
        configContent = jsonEncode(cfg);
      } catch (_) {
        configContent = conn.configJson!;
      }
    } else {
      // Fallback: build from individual fields
      final user = conn.password != null ? 'admin:${conn.password}' : 'admin';
      configContent = jsonEncode({
        'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
        'proxy': 'https://$user@${conn.serverIp}:${conn.port}',
        'log': '',
      });
    }

    final configPath = await _writeTempConfig(
        AppConstants.naiveConfigFile, configContent);
    _tempConfigPath = configPath;

    final outputBuffer = StringBuffer();

    _process = await Process.start(
      naivePath,
      ['--config=$configPath'],
      runInShell: false,
    );
    _activeEngine = EngineType.naive;

    _process!.stderr.transform(utf8.decoder).listen((s) => outputBuffer.write(s));
    _process!.stdout.transform(utf8.decoder).listen((s) => outputBuffer.write(s));

    // Wait 1s and check process is still alive
    await Future.delayed(const Duration(milliseconds: 1000));

    try {
      final code = await _process!.exitCode
          .timeout(const Duration(milliseconds: 50));
      final err = outputBuffer.toString().trim();
      throw VpnEngineException(
          'naive.exe crashed (exit $code)${err.isNotEmpty ? ':\n$err' : ''}');
    } on TimeoutException {
      // Still running — good
    }

    await _setSystemProxy(enabled: true);
    status.value = VpnStatus.connected;

    _process!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final err = outputBuffer.toString().trim();
        final tail = err.length > 300 ? err.substring(err.length - 300) : err;
        status.value = VpnStatus.error;
        lastError.value =
            'naive exited (code $code)${tail.isNotEmpty ? ':\n$tail' : ''}';
      }
    });
  }

  // ── System proxy ──────────────────────────────────────────────────────────

  Future<void> _setSystemProxy({required bool enabled}) async {
    if (!Platform.isWindows) return;
    try {
      if (enabled) {
        final proxyAddr = '127.0.0.1:${AppConstants.xraySocksPort}';
        // WinINet (Chrome/Edge/IE)
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '1', '/f',
        ]);
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyServer', '/t', 'REG_SZ',
          '/d', 'socks=$proxyAddr', '/f',
        ]);
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyOverride', '/t', 'REG_SZ',
          '/d', 'localhost;127.*;10.*;172.16.*;192.168.*;<local>', '/f',
        ]);
        // System-wide winhttp
        await Process.run('netsh', [
          'winhttp', 'set', 'proxy', proxyAddr,
          'bypass-list=localhost;127.*;10.*;172.16.*;192.168.*',
        ]);
      } else {
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '0', '/f',
        ]);
        await Process.run('netsh', ['winhttp', 'reset', 'proxy']);
      }
    } catch (_) {}
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  Future<String> _engineDir() async {
    return await EngineDownloader.instance.enginesDir;
  }

  Future<String> _writeTempConfig(String filename, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file = File(p.join(appDir.path, filename));
    await file.writeAsString(content);
    return file.path;
  }

  Future<void> _stopCurrentProcess() async {
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgInstallPath).existsSync()) {
          await Process.run(_awgInstallPath, ['/removetunnel', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    } else if (_process != null) {
      try {
        _process!.kill(ProcessSignal.sigterm);
        await _process!.exitCode
            .timeout(const Duration(seconds: 3))
            .catchError((_) => -1);
        _process!.kill(ProcessSignal.sigkill);
      } catch (_) {}
    }

    _process = null;
    _activeEngine = null;

    if (Platform.isWindows) {
      await _setSystemProxy(enabled: false);
    }
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
  VpnEngineException(message) : message = message.toString();
  @override
  String toString() => 'VpnEngineException: $message';
}
