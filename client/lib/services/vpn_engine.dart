// VPN Engine — manages VPN subprocesses on Windows
//
// Architecture:
//   VLESS/Trojan  → xray.exe (SOCKS5 on 10808) + tun2socks.exe (TUN adapter)
//   NaiveProxy    → naive.exe (SOCKS5 on 10808) + tun2socks.exe (TUN adapter)
//   AmneziaWG     → amneziawg.exe /installtunnelservice (Windows tunnel service)
//
// tun2socks creates a virtual TUN network adapter and routes ALL OS traffic
// through the local SOCKS5 proxy — works for every app, browser, game, etc.

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

  Process? _proxyProcess;    // xray.exe or naive.exe
  Process? _tun2socksProcess; // tun2socks.exe
  EngineType? _activeEngine;
  String? _tempConfigPath;
  String? _awgTunnelName;

  static const _tunName = 'MilkyVPN-TUN';
  static const _tunAddr = '198.18.0.1';   // virtual TUN IP (RFC 5737 test range)
  static const _tunGw   = '198.18.0.2';   // gateway inside TUN

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
      status.value = VpnStatus.error;
      lastError.value = e.toString().replaceFirst('VpnEngineException: ', '');
      // Clean up any partial start
      await _killAllProcesses();
      rethrow;
    }
  }

  // ── Public: disconnect ────────────────────────────────────────────────────

  Future<void> disconnect() async {
    if (status.value == VpnStatus.disconnected) return;
    status.value = VpnStatus.disconnecting;
    await _killAllProcesses();
    await _cleanupTempConfig();
    status.value = VpnStatus.disconnected;
  }

  // ── XRAY + tun2socks ──────────────────────────────────────────────────────

  Future<void> _startXrayWithTun(VpnConnection conn, String engineDir) async {
    final xrayPath = p.join(engineDir, AppConstants.xrayExe);
    if (!File(xrayPath).existsSync()) {
      throw VpnEngineException('xray.exe not found. Run setup again.');
    }

    // Write xray config
    final config = _buildXrayClientConfig(conn);
    final configPath = await _writeTempConfig(
        AppConstants.xrayConfigFile, jsonEncode(config));
    _tempConfigPath = configPath;

    final stderrBuf = StringBuffer();

    // Start xray
    _proxyProcess = await Process.start(
      xrayPath,
      ['run', '-config', configPath],
      workingDirectory: engineDir, // so xray finds geoip.dat / geosite.dat
      runInShell: false,
    );
    _activeEngine = EngineType.xray;
    _proxyProcess!.stderr.transform(utf8.decoder).listen((s) => stderrBuf.write(s));
    _proxyProcess!.stdout.transform(utf8.decoder).listen((s) => stderrBuf.write(s));

    // Give xray 1.5s to start
    await Future.delayed(const Duration(milliseconds: 1500));
    await _checkProcessAlive(_proxyProcess!, 'xray.exe', stderrBuf);

    // Remember server IP so we can add a direct route for it (avoid loop)
    _vpnServerIp = conn.serverIp;

    // Start tun2socks to route all traffic through xray's SOCKS5
    await _startTun2socks(engineDir);

    status.value = VpnStatus.connected;

    // Monitor xray
    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final tail = _tail(stderrBuf.toString(), 300);
        status.value = VpnStatus.error;
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
      ],
      'outbounds': [
        {...outbound, 'tag': 'proxy'},
        {'tag': 'direct', 'protocol': 'freedom'},
      ],
      'routing': {
        'domainStrategy': 'IPIfNonMatch',
        'rules': [
          // Don't proxy the VPN server itself (avoid loop)
          {
            'type': 'field',
            'ip': [conn.serverIp],
            'outboundTag': 'direct',
          },
          // Private IPs go direct
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

  // ── NaiveProxy + tun2socks ────────────────────────────────────────────────

  Future<void> _startNaiveWithTun(VpnConnection conn, String engineDir) async {
    final naivePath = p.join(engineDir, AppConstants.naiveExe);
    if (!File(naivePath).existsSync()) {
      throw VpnEngineException('naive.exe not found. Run setup again.');
    }

    // Use config_json from backend (has correct proxy URL + credentials)
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

    final outputBuf = StringBuffer();

    _proxyProcess = await Process.start(
      naivePath,
      ['--config=$configPath'],
      runInShell: false,
    );
    _activeEngine = EngineType.naive;
    _proxyProcess!.stderr.transform(utf8.decoder).listen((s) => outputBuf.write(s));
    _proxyProcess!.stdout.transform(utf8.decoder).listen((s) => outputBuf.write(s));

    await Future.delayed(const Duration(milliseconds: 1000));
    await _checkProcessAlive(_proxyProcess!, 'naive.exe', outputBuf);

    // Remember server IP for direct route (avoid loop)
    _vpnServerIp = conn.serverIp;

    // Start tun2socks
    await _startTun2socks(engineDir);

    status.value = VpnStatus.connected;

    _proxyProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        final tail = _tail(outputBuf.toString(), 300);
        status.value = VpnStatus.error;
        lastError.value = 'naive завершился (код $code)${tail.isNotEmpty ? ":\n$tail" : ""}';
        _killAllProcesses();
      }
    });
  }

  // ── tun2socks ─────────────────────────────────────────────────────────────
  //
  // tun2socks creates a virtual TUN adapter and forwards all traffic to
  // the local SOCKS5 proxy (xray or naive).
  //
  // After starting tun2socks we:
  //   1. Add default route via TUN gateway (all traffic → TUN)
  //   2. Add specific route for VPN server via original gateway (avoid loop)

  Future<void> _startTun2socks(String engineDir) async {
    final tun2socksPath = p.join(engineDir, 'tun2socks.exe');
    if (!File(tun2socksPath).existsSync()) {
      throw VpnEngineException('tun2socks.exe not found. Run setup again.');
    }

    final t2sBuf = StringBuffer();

    _tun2socksProcess = await Process.start(
      tun2socksPath,
      [
        '-device', 'tun://$_tunName',
        '-proxy', 'socks5://127.0.0.1:${AppConstants.xraySocksPort}',
        '-interface', '', // use default interface
        '-loglevel', 'warning',
      ],
      runInShell: false,
    );

    _tun2socksProcess!.stderr.transform(utf8.decoder).listen((s) => t2sBuf.write(s));
    _tun2socksProcess!.stdout.transform(utf8.decoder).listen((s) => t2sBuf.write(s));

    // Wait for TUN adapter to come up
    await Future.delayed(const Duration(seconds: 2));
    await _checkProcessAlive(_tun2socksProcess!, 'tun2socks.exe', t2sBuf);

    // Set up routing: all traffic via TUN, but VPN server goes direct
    await _setupRoutes(add: true);

    // Monitor tun2socks
    _tun2socksProcess!.exitCode.then((code) {
      if (status.value == VpnStatus.connected) {
        status.value = VpnStatus.error;
        lastError.value = 'tun2socks завершился неожиданно (код $code)';
        _killAllProcesses();
      }
    });
  }

  // ── AWG (AmneziaWG) — Windows Tunnel Service ──────────────────────────────
  //
  // amneziawg.exe /installtunnelservice CONFIG_PATH  — install & start tunnel
  // amneziawg.exe /uninstalltunnelservice TUNNEL_NAME — stop & remove tunnel
  //
  // AWG manages its own routing (AllowedIPs = 0.0.0.0/0), no tun2socks needed.

  static const _awgExePath = r'C:\Program Files\AmneziaWG\amneziawg.exe';

  Future<void> _startAwg(VpnConnection conn, String engineDir) async {
    if (!File(_awgExePath).existsSync()) {
      throw VpnEngineException(
          'AmneziaWG не установлен.\n'
          'Скачайте MSI: https://github.com/amnezia-vpn/amneziawg-windows-client/releases\n'
          '(файл amneziawg-amd64-2.0.0.msi)');
    }

    final confText = conn.configJson ?? _buildAwgConfig(conn);
    final tunnelName = 'MilkyVPN${conn.id}'; // no underscore — simpler service name
    _awgTunnelName = tunnelName;

    // Write config — path must have no spaces
    final appDir = await getApplicationSupportDirectory();
    final confFile = File(p.join(appDir.path, '$tunnelName.conf'));
    await confFile.writeAsString(confText);
    _tempConfigPath = confFile.path;

    // Remove stale tunnel first (ignore errors)
    await Process.run(_awgExePath, ['/uninstalltunnelservice', tunnelName]);
    await Future.delayed(const Duration(milliseconds: 800));

    // Install tunnel service
    final result = await Process.run(
      _awgExePath,
      ['/installtunnelservice', confFile.path],
    );

    if (result.exitCode != 0) {
      final err = '${result.stdout}\n${result.stderr}'.trim();
      throw VpnEngineException('AWG install failed (exit ${result.exitCode}): $err');
    }

    // Wait for service to start
    await Future.delayed(const Duration(seconds: 3));

    // Verify service is running
    final sc = await Process.run(
      'sc', ['query', 'AmneziaWGTunnel\$$tunnelName'],
      runInShell: true,
    );
    final scOut = sc.stdout.toString();
    if (!scOut.contains('RUNNING') && !scOut.contains('START_PENDING')) {
      // Try to get more info from event log
      throw VpnEngineException('AWG tunnel не запустился.\n'
          'Убедитесь что AmneziaWG установлен корректно.\nSC: $scOut');
    }

    _activeEngine = EngineType.awg;
    status.value = VpnStatus.connected;
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
          status.value = VpnStatus.error;
          lastError.value = 'AWG туннель остановился неожиданно';
          _killAllProcesses();
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
        'S1 = $s1\nS2 = $s2\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n\n'
        '[Peer]\n'
        'PublicKey = ${conn.wgPublicKey ?? ''}\n'
        'PresharedKey = ${conn.wgPresharedKey ?? ''}\n'
        'Endpoint = ${conn.serverIp}:${conn.port}\n'
        'AllowedIPs = 0.0.0.0/0, ::/0\n'
        'PersistentKeepalive = 25\n';
  }

  // ── Routing helpers ───────────────────────────────────────────────────────

  String? _originalGateway;
  String? _vpnServerIp;

  Future<void> _setupRoutes({required bool add}) async {
    if (!Platform.isWindows) return;
    try {
      if (add) {
        // Get current default gateway before changing routes
        final gwResult = await Process.run(
          'powershell', ['-Command',
            '(Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric | Select-Object -First 1).NextHop'
          ],
          runInShell: false,
        );
        _originalGateway = gwResult.stdout.toString().trim();

        // Get TUN adapter index
        await Future.delayed(const Duration(milliseconds: 500));
        final idxResult = await Process.run(
          'powershell', ['-Command',
            '(Get-NetAdapter | Where-Object {$_.Name -like "*$_tunName*"} | Select-Object -First 1).ifIndex'
          ],
          runInShell: false,
        );
        final tunIdx = idxResult.stdout.toString().trim();

        if (tunIdx.isNotEmpty && _originalGateway != null && _originalGateway!.isNotEmpty) {
          // Route VPN server IP through original gateway (prevent loop)
          if (_vpnServerIp != null) {
            await Process.run('route', [
              'add', _vpnServerIp!, 'mask', '255.255.255.255', _originalGateway!,
            ], runInShell: true);
          }
          // Assign IP to TUN adapter
          await Process.run('netsh', [
            'interface', 'ip', 'set', 'address',
            'name=$_tunName', 'static', _tunAddr, '255.255.255.0', _tunGw,
          ], runInShell: true);
          // Route all traffic through TUN
          await Process.run('route', [
            'add', '0.0.0.0', 'mask', '0.0.0.0', _tunGw, 'metric', '5',
          ], runInShell: true);
        }
      } else {
        // Remove routes on disconnect
        await Process.run('route', ['delete', '0.0.0.0', 'mask', '0.0.0.0', _tunGw],
            runInShell: true);
        if (_vpnServerIp != null && _originalGateway != null) {
          await Process.run('route', ['delete', _vpnServerIp!, 'mask', '255.255.255.255'],
              runInShell: true);
        }
        _originalGateway = null;
        _vpnServerIp = null;
      }
    } catch (e) {
      // Non-fatal — log but continue
      debugPrint('Route setup error: $e');
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  Future<void> _checkProcessAlive(
      Process proc, String name, StringBuffer buf) async {
    try {
      final code = await proc.exitCode
          .timeout(const Duration(milliseconds: 50));
      final err = _tail(buf.toString(), 500);
      throw VpnEngineException(
          '$name crashed (exit $code)${err.isNotEmpty ? ":\n$err" : ""}');
    } on TimeoutException {
      // Still running — good
    }
  }

  String _tail(String s, int maxLen) {
    s = s.trim();
    return s.length > maxLen ? s.substring(s.length - maxLen) : s;
  }

  Future<String> _engineDir() async {
    return await EngineDownloader.instance.enginesDir;
  }

  Future<String> _writeTempConfig(String filename, String content) async {
    final appDir = await getApplicationSupportDirectory();
    final file = File(p.join(appDir.path, filename));
    await file.writeAsString(content);
    return file.path;
  }

  Future<void> _killAllProcesses() async {
    // Remove AWG tunnel service
    if (_activeEngine == EngineType.awg && _awgTunnelName != null) {
      try {
        if (File(_awgExePath).existsSync()) {
          await Process.run(_awgExePath, ['/uninstalltunnelservice', _awgTunnelName!]);
        }
      } catch (_) {}
      _awgTunnelName = null;
    }

    // Kill tun2socks
    if (_tun2socksProcess != null) {
      try {
        _tun2socksProcess!.kill();
        await _tun2socksProcess!.exitCode
            .timeout(const Duration(seconds: 2))
            .catchError((_) => -1);
      } catch (_) {}
      _tun2socksProcess = null;
    }

    // Kill proxy process
    if (_proxyProcess != null) {
      try {
        _proxyProcess!.kill();
        await _proxyProcess!.exitCode
            .timeout(const Duration(seconds: 2))
            .catchError((_) => -1);
      } catch (_) {}
      _proxyProcess = null;
    }

    // Remove routes
    if (_activeEngine != EngineType.awg) {
      await _setupRoutes(add: false);
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
