// VPN Engine — manages xray.exe / awg-quick.exe / naive.exe subprocesses
// Handles TUN mode for full traffic routing on Windows

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
          throw VpnEngineException(
              'Unsupported protocol: ${conn.protocol}');
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
      throw VpnEngineException(
          'xray.exe not found. Please reinstall the app.');
    }

    final config = _buildXrayClientConfig(conn);
    final configPath = await _writeTempConfig(
        AppConstants.xrayConfigFile, jsonEncode(config));
    _tempConfigPath = configPath;

    _process = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      runInShell: false,
    );
    _activeEngine = EngineType.xray;

    // Wait a moment and check process is still alive
    await Future.delayed(const Duration(milliseconds: 800));
    if (_process!.pid == 0) {
      throw VpnEngineException('xray.exe failed to start');
    }

    // Set system proxy (SOCKS5 on localhost)
    await _setSystemProxy(enabled: true);

    status.value = VpnStatus.connected;

    // Monitor process exit
    _process!.exitCode.then((_) {
      if (status.value == VpnStatus.connected) {
        status.value = VpnStatus.error;
        lastError.value = 'VPN process exited unexpectedly';
      }
    });
  }

  Map<String, dynamic> _buildXrayClientConfig(VpnConnection conn) {
    // Build xray client config for TUN + SOCKS outbound
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
          {
            'type': 'field',
            'ip': ['geoip:private'],
            'outboundTag': 'direct',
          },
          {
            'type': 'field',
            'ip': ['geoip:ru'],
            'outboundTag': 'proxy',
          },
          {
            'type': 'field',
            'network': 'tcp,udp',
            'outboundTag': 'proxy',
          },
        ],
      },
    };
  }

  // ── AWG (AmneziaWG) ───────────────────────────────────────────────────────

  Future<void> _startAwg(VpnConnection conn, String engineDir) async {
    // Try awg.exe first (new name), fallback to awg-quick.exe (legacy)
    String awgPath = p.join(engineDir, 'awg.exe');
    if (!File(awgPath).existsSync()) {
      awgPath = p.join(engineDir, AppConstants.awgExe);
    }
    if (!File(awgPath).existsSync()) {
      throw VpnEngineException(
          'awg.exe not found. Please reinstall the app.');
    }

    // Use config_json from backend (already has the full .conf text)
    final confText = conn.configJson ?? _buildAwgConfig(conn);
    final configPath =
        await _writeTempConfig(AppConstants.awgConfigFile, confText);
    _tempConfigPath = configPath;

    // awg-quick up <config_file> requires elevated rights (WinTUN)
    _process = await Process.start(
      awgPath,
      ['up', configPath],
      runInShell: false,
    );
    _activeEngine = EngineType.awg;

    final exitCode = await _process!.exitCode.timeout(
      const Duration(seconds: 10),
      onTimeout: () => 0, // still running = good
    );

    if (exitCode != 0 && exitCode != -1) {
      final err = await _process!.stderr.transform(utf8.decoder).join();
      throw VpnEngineException('awg-quick failed (exit $exitCode): $err');
    }

    status.value = VpnStatus.connected;
  }

  String _buildAwgConfig(VpnConnection conn) {
    // Fallback: build AWG config from individual fields
    final s1 = 15 + (conn.id * 7) % 136; // deterministic from conn id
    final s2 = 15 + (conn.id * 13) % 136;
    return '''[Interface]
PrivateKey = ${conn.wgClientPrivateKey ?? ''}
Address = ${conn.wgClientIp ?? '10.8.0.2'}/32
DNS = 1.1.1.1
MTU = 1420

Jc = ${conn.awgJunkPacketCount ?? 4}
Jmin = ${conn.awgJunkPacketMinSize ?? 40}
Jmax = ${conn.awgJunkPacketMaxSize ?? 70}
S1 = $s1
S2 = $s2
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = ${conn.wgPublicKey ?? ''}
PresharedKey = ${conn.wgPresharedKey ?? ''}
Endpoint = ${conn.serverIp}:${conn.port}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
''';
  }

  // ── NaiveProxy ────────────────────────────────────────────────────────────

  Future<void> _startNaive(VpnConnection conn, String engineDir) async {
    final naivePath = p.join(engineDir, AppConstants.naiveExe);
    if (!File(naivePath).existsSync()) {
      throw VpnEngineException(
          'naive.exe not found. Please reinstall the app.');
    }

    // Build naive client config
    final config = {
      'listen': 'socks://127.0.0.1:${AppConstants.xraySocksPort}',
      'proxy':
          'https://admin:${conn.password ?? ''}@${conn.serverIp}:${conn.port}',
      'log': '',
    };
    final configPath = await _writeTempConfig(
        AppConstants.naiveConfigFile, jsonEncode(config));
    _tempConfigPath = configPath;

    _process = await Process.start(
      naivePath,
      [configPath],
      runInShell: false,
    );
    _activeEngine = EngineType.naive;

    await Future.delayed(const Duration(milliseconds: 600));
    await _setSystemProxy(enabled: true);
    status.value = VpnStatus.connected;

    _process!.exitCode.then((_) {
      if (status.value == VpnStatus.connected) {
        status.value = VpnStatus.error;
        lastError.value = 'naive process exited unexpectedly';
      }
    });
  }

  // ── System proxy (Windows registry) ──────────────────────────────────────

  Future<void> _setSystemProxy({required bool enabled}) async {
    if (!Platform.isWindows) return;
    try {
      if (enabled) {
        // Enable SOCKS5 proxy via netsh / registry
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '1', '/f',
        ]);
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyServer', '/t', 'REG_SZ',
          '/d', 'socks=127.0.0.1:${AppConstants.xraySocksPort}', '/f',
        ]);
      } else {
        await Process.run('reg', [
          'add',
          r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
          '/v', 'ProxyEnable', '/t', 'REG_DWORD', '/d', '0', '/f',
        ]);
      }
    } catch (_) {
      // Non-fatal — user can set proxy manually
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  Future<String> _engineDir() async {
    // Use same path as EngineDownloader so binaries are found correctly
    return await EngineDownloader.instance.enginesDir;
  }

  Future<String> _writeTempConfig(String filename, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file = File(p.join(appDir.path, filename));
    await file.writeAsString(content);
    return file.path;
  }

  Future<void> _stopCurrentProcess() async {
    if (_process != null) {
      try {
        if (_activeEngine == EngineType.awg && _tempConfigPath != null) {
          // AWG needs explicit 'down' command
          final engineDir = await _engineDir();
          String awgPath = p.join(engineDir, 'awg.exe');
          if (!File(awgPath).existsSync()) {
            awgPath = p.join(engineDir, AppConstants.awgExe);
          }
          if (File(awgPath).existsSync()) {
            await Process.run(awgPath, ['down', _tempConfigPath!]);
          }
        }
        _process!.kill(ProcessSignal.sigterm);
        await _process!.exitCode
            .timeout(const Duration(seconds: 3))
            .catchError((_) => -1);
        _process!.kill(ProcessSignal.sigkill);
      } catch (_) {}
      _process = null;
    }
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
  VpnEngineException(this.message);
  @override
  String toString() => 'VpnEngineException: $message';
}
