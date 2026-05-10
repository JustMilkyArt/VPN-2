// HomeScreen — main app window

import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';
import '../models/connection.dart';
import '../services/vpn_provider.dart';
import '../widgets/connection_card.dart';
import '../widgets/connect_button.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<VpnProvider>().loadConnections();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D0F14),
      body: Column(
        children: [
          _TitleBar(),
          Expanded(
            child: Row(
              children: [
                // Left panel: connection list
                _ConnectionsPanel(),
                // Right panel: connect button + status
                _ConnectPanel(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Title bar (custom, frameless window) ─────────────────────────────────────

class _TitleBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      height: 52,
      decoration: BoxDecoration(
        color: const Color(0xFF141720),
        border: Border(
          bottom: BorderSide(
            color: Colors.white.withValues(alpha: 0.06),
          ),
        ),
      ),
      child: Row(
        children: [
          const SizedBox(width: 20),
          // Logo / app name
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF4F8EF7), Color(0xFF7B61FF)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(7),
            ),
            child: const Icon(
              Icons.shield_rounded,
              color: Colors.white,
              size: 17,
            ),
          ),
          const SizedBox(width: 10),
          const Text(
            'MilkyVPN',
            style: TextStyle(
              color: Colors.white,
              fontSize: 15,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.3,
            ),
          ),
          const Spacer(),
          // Refresh button
          Consumer<VpnProvider>(
            builder: (_, prov, __) => IconButton(
              icon: Icon(
                Icons.refresh_rounded,
                color: Colors.white.withValues(alpha: 0.4),
                size: 18,
              ),
              tooltip: 'Обновить список',
              onPressed: prov.loadState == LoadState.loading
                  ? null
                  : () => prov.loadConnections(forceRefresh: true),
            ),
          ),
          // Minimize to tray
          IconButton(
            icon: Icon(
              Icons.minimize_rounded,
              color: Colors.white.withValues(alpha: 0.4),
              size: 18,
            ),
            tooltip: 'Свернуть в трей',
            onPressed: () {
              // Handled by window_manager in main.dart
              _minimizeToTray(context);
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
    );
  }

  void _minimizeToTray(BuildContext context) async {
    if (Platform.isWindows) {
      try {
        await windowManager.hide();
      } catch (_) {}
    }
  }
}

// ── Left panel: connections list ─────────────────────────────────────────────

class _ConnectionsPanel extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 320,
      child: Container(
        decoration: BoxDecoration(
          border: Border(
            right: BorderSide(
              color: Colors.white.withValues(alpha: 0.06),
            ),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _SectionHeader(
              title: 'Подключения',
              trailing: Consumer<VpnProvider>(
                builder: (_, prov, __) {
                  if (prov.loadState == LoadState.loading) {
                    return const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Color(0xFF4F8EF7),
                      ),
                    );
                  }
                  return Text(
                    '${prov.connections.length}',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.3),
                      fontSize: 13,
                    ),
                  );
                },
              ),
            ),
            Expanded(child: _ConnectionList()),
          ],
        ),
      ),
    );
  }
}

class _ConnectionList extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<VpnProvider>(
      builder: (context, prov, _) {
        if (prov.loadState == LoadState.loading &&
            prov.connections.isEmpty) {
          return const Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(
                  color: Color(0xFF4F8EF7),
                  strokeWidth: 2.5,
                ),
                SizedBox(height: 16),
                Text(
                  'Загрузка подключений…',
                  style: TextStyle(
                    color: Color(0xFF888CA4),
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          );
        }

        if (prov.loadState == LoadState.error && prov.connections.isEmpty) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.wifi_off_rounded,
                    size: 42,
                    color: Colors.white.withValues(alpha: 0.2),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    prov.loadError ?? 'Ошибка загрузки',
                    style: const TextStyle(
                      color: Color(0xFFFF4D6D),
                      fontSize: 13,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    onPressed: () => prov.loadConnections(forceRefresh: true),
                    icon: const Icon(Icons.refresh_rounded, size: 16),
                    label: const Text('Повторить'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFF4F8EF7),
                      side: const BorderSide(color: Color(0xFF4F8EF7)),
                    ),
                  ),
                ],
              ),
            ),
          );
        }

        if (prov.connections.isEmpty) {
          return Center(
            child: Text(
              'Нет доступных подключений',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.3),
                fontSize: 13,
              ),
            ),
          );
        }

        return ListView.builder(
          padding: const EdgeInsets.only(top: 6, bottom: 12),
          itemCount: prov.connections.length,
          itemBuilder: (context, i) {
            final conn = prov.connections[i];
            final isSelected = prov.selectedConnection?.id == conn.id;
            final isActive = prov.isConnected &&
                prov.selectedConnection?.id == conn.id;
            return ConnectionCard(
              connection: conn,
              isSelected: isSelected,
              isActiveVpn: isActive,
              onTap: () {
                if (prov.isConnected || prov.isBusy) return;
                prov.selectConnection(conn);
              },
            );
          },
        );
      },
    );
  }
}

// ── Right panel: connect button + status ─────────────────────────────────────

class _ConnectPanel extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Consumer<VpnProvider>(
        builder: (context, prov, _) {
          final selected = prov.selectedConnection;
          return Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Server info
              if (selected != null) ...[
                Text(
                  selected.countryFlag,
                  style: const TextStyle(fontSize: 38),
                ),
                const SizedBox(height: 8),
                Text(
                  selected.serverName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _ProtoChip(label: selected.protoLabel),
                    const SizedBox(width: 6),
                    _TypeChipSmall(conn: selected),
                  ],
                ),
                const SizedBox(height: 36),
              ] else ...[
                const SizedBox(height: 80),
              ],
              // Big connect button
              ConnectButton(
                status: prov.vpnStatus,
                onPressed: selected == null
                    ? null
                    : () => _onConnectPressed(context, prov),
              ),
              const SizedBox(height: 28),
              // Status text
              _StatusText(status: prov.vpnStatus, error: prov.vpnError),
              const SizedBox(height: 20),
              // IP checker — показывает реальный IP когда подключено
              if (prov.isConnected) const _IpChecker(),
              const SizedBox(height: 40),
            ],
          );
        },
      ),
    );
  }

  void _onConnectPressed(BuildContext context, VpnProvider prov) {
    if (prov.isConnected) {
      prov.disconnect();
    } else {
      prov.connect();
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String title;
  final Widget? trailing;
  const _SectionHeader({required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 16, 10),
      child: Row(
        children: [
          Text(
            title,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5),
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.2,
            ),
          ),
          const Spacer(),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class _ProtoChip extends StatelessWidget {
  final String label;
  const _ProtoChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: const Color(0xFF7B61FF).withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
        border:
            Border.all(color: const Color(0xFF7B61FF).withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Color(0xFF7B61FF),
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _TypeChipSmall extends StatelessWidget {
  final VpnConnection conn;
  const _TypeChipSmall({required this.conn});

  @override
  Widget build(BuildContext context) {
    final isCascade = conn.connType == ConnectionType.cascade;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: (isCascade
                ? const Color(0xFFFF8A00)
                : const Color(0xFF00D26A))
            .withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        isCascade ? 'Каскад' : 'Прямое',
        style: TextStyle(
          color: isCascade ? const Color(0xFFFF8A00) : const Color(0xFF00D26A),
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _StatusText extends StatelessWidget {
  final VpnStatus status;
  final String? error;
  const _StatusText({required this.status, this.error});

  @override
  Widget build(BuildContext context) {
    final (text, color) = switch (status) {
      VpnStatus.connected     => ('Защищено', const Color(0xFF00D26A)),
      VpnStatus.connecting    => ('Устанавливается соединение…', const Color(0xFF7B61FF)),
      VpnStatus.disconnecting => ('Отключение…', const Color(0xFFFF8A00)),
      VpnStatus.error         => (error ?? 'Ошибка подключения', const Color(0xFFFF4D6D)),
      VpnStatus.disconnected  => ('Не защищено', Colors.white38),
    };

    return Text(
      text,
      style: TextStyle(
        color: color,
        fontSize: 13,
        fontWeight: status == VpnStatus.connected
            ? FontWeight.w600
            : FontWeight.w400,
      ),
      textAlign: TextAlign.center,
    );
  }
}

// ── IP Checker — показывает реальный IP после подключения ────────────────────
// Помогает пользователю убедиться что VPN работает:
//   ✅ Если IP не российский — VPN работает
//   ❌ Если IP российский   — трафик не идёт через туннель

class _IpChecker extends StatefulWidget {
  const _IpChecker();

  @override
  State<_IpChecker> createState() => _IpCheckerState();
}

class _IpCheckerState extends State<_IpChecker> {
  String? _ip;
  String? _country;
  int?    _rttMs;
  bool    _loading = true;
  bool    _isRu    = false;
  Timer?  _timer;

  @override
  void initState() {
    super.initState();
    _checkIp();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _checkIp());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _checkIp() async {
    if (!mounted) return;
    setState(() => _loading = true);
    try {
      final t0   = DateTime.now();
      // ВАЖНО: Flutter на Windows использует WinHTTP, который НЕ следует
      // маршрутной таблице ядра и обходит TUN-адаптер.
      // Решение: делаем HTTP-запрос вручную через raw SOCKS5-сокет
      // (127.0.0.1:10808 = xray/naive SOCKS5 прокси), который точно
      // идёт через VPN-туннель.
      final body = await _httpViaSocks5(
        'ip-api.com', 80,
      ).timeout(const Duration(seconds: 10));
      final rtt  = DateTime.now().difference(t0).inMilliseconds;
      if (!mounted) return;
      final ip      = _extract(body, 'query');
      final country = _extract(body, 'country');
      final cc      = _extract(body, 'countryCode');
      if (ip.isNotEmpty) {
        setState(() {
          _ip      = ip;
          _country = country;
          _rttMs   = rtt;
          _isRu    = cc == 'RU';
          _loading = false;
        });
      } else {
        setState(() { _ip = '—'; _rttMs = null; _loading = false; });
      }
    } catch (_) {
      if (mounted) setState(() { _ip = 'Нет ответа'; _rttMs = null; _loading = false; });
    }
  }

  /// HTTP GET через SOCKS5 (127.0.0.1:10808) — обходит WinHTTP.
  ///
  /// xray и naive оба открывают SOCKS5 на порту 10808.
  /// AWG не открывает SOCKS5 — для него фоллбэк на системный http.get(),
  /// который корректен т.к. AWG пишет маршруты прямо в ядро через WinTUN.
  ///
  /// ВАЖНО про смещения (RFC 1928):
  ///   Greeting reply:  [VER=05][METHOD=00]          → 2 байта, offset 0
  ///   CONNECT reply:   [VER][REP][RSV][ATYP][ADDR][PORT]
  ///                    начинается с offset 2 в allBytes
  ///     ATYP=01(IPv4) → ADDR=4B + PORT=2B → всего с offset 2: 4+4+2=10 байт
  ///     ATYP=04(IPv6) → ADDR=16B + PORT=2B → 4+16+2=22 байт
  ///     ATYP=03(dom)  → 1B_len + NB_dom + PORT=2B → 4+1+N+2 байт
  ///   allBytes.length нужен >= (2 + размер_CONNECT_reply) до отправки HTTP.
  Future<String> _httpViaSocks5(String host, int remotePort) async {
    const socksHost = '127.0.0.1';
    const socksPort = 10808;

    try {
      final sock = await Socket.connect(
        socksHost, socksPort,
        timeout: const Duration(seconds: 4),
      );
      sock.setOption(SocketOption.tcpNoDelay, true);

      // allBytes — единый накопитель всех входящих байт с начала соединения.
      // Все need(n) ждут allBytes.length >= n (абсолютный счётчик).
      final allBytes  = <int>[];
      final done      = Completer<void>();

      final sub = sock.listen(
        allBytes.addAll,
        onDone:  () { if (!done.isCompleted) done.complete(); },
        onError: (e) { if (!done.isCompleted) done.completeError(e); },
        cancelOnError: true,
      );

      // Ждём появления >= n байт суммарно (poll каждые 10 мс, до deadline)
      Future<void> need(int n, Duration timeout) async {
        final deadline = DateTime.now().add(timeout);
        while (allBytes.length < n) {
          if (DateTime.now().isAfter(deadline)) {
            throw TimeoutException('SOCKS5: нет ответа ($n байт) за ${timeout.inSeconds}с');
          }
          await Future<void>.delayed(const Duration(milliseconds: 10));
        }
      }

      try {
        // ── 1. Greeting: VER=5, NMETHODS=1, METHOD=0(noauth) ────────
        //    Reply: 2 байта → allBytes[0]=VER, allBytes[1]=METHOD
        sock.add([0x05, 0x01, 0x00]);
        await sock.flush();

        await need(2, const Duration(seconds: 4));
        if (allBytes[0] != 0x05 || allBytes[1] != 0x00) {
          throw Exception('SOCKS5 auth rejected (method=0x${allBytes[1].toRadixString(16)})');
        }

        // ── 2. CONNECT request (ATYP=0x03 domain) ───────────────────
        final hb = host.codeUnits;           // ASCII hostname bytes
        sock.add([
          0x05, 0x01, 0x00, 0x03,            // VER CMD RSV ATYP=domain
          hb.length, ...hb,                  // 1-byte len + hostname bytes
          (remotePort >> 8) & 0xFF, remotePort & 0xFF,
        ]);
        await sock.flush();

        // ── 3. CONNECT reply — начинается с offset 2 в allBytes ──────
        //    Сначала читаем 4-байтный заголовок: VER REP RSV ATYP
        //    В allBytes это индексы [2],[3],[4],[5].
        await need(2 + 4, const Duration(seconds: 5));   // offset 2..5
        final rep  = allBytes[3];   // REP (0=успех)
        final atyp = allBytes[5];   // ATYP
        if (rep != 0x00) {
          throw Exception('SOCKS5 CONNECT failed rep=0x${rep.toRadixString(16)}');
        }

        // Считаем полный размер CONNECT reply (с учётом ATYP):
        //   IPv4:   4(заг) + 4(addr) + 2(port) = 10
        //   IPv6:   4(заг) + 16(addr) + 2(port) = 22
        //   domain: 4(заг) + 1(len) + N(dom) + 2(port)
        //           Для domain-reply сначала читаем 1 байт длины.
        final int connectReplyLen;
        if (atyp == 0x01) {
          connectReplyLen = 10;          // IPv4
        } else if (atyp == 0x04) {
          connectReplyLen = 22;          // IPv6
        } else {
          // ATYP=0x03: следующий байт (offset 2+4=6) — длина домена
          await need(2 + 4 + 1, const Duration(seconds: 5));
          final domLen = allBytes[6];
          connectReplyLen = 4 + 1 + domLen + 2;
        }
        await need(2 + connectReplyLen, const Duration(seconds: 5));

        // ── 4. HTTP GET — теперь туннель открыт ─────────────────────
        sock.write(
          'GET /json/?fields=query,country,countryCode HTTP/1.1\r\n'
          'Host: $host\r\n'
          'Connection: close\r\n'
          '\r\n',
        );
        await sock.flush();

        // Читаем до закрытия TCP-соединения (сервер присылает Connection:close)
        await done.future.timeout(const Duration(seconds: 8));

        // HTTP-ответ начинается сразу за SOCKS5-оберткой:
        // allBytes = [greeting_reply(2)] + [connect_reply(N)] + [HTTP response]
        final raw = String.fromCharCodes(allBytes);
        final sep = raw.indexOf('\r\n\r\n');
        return sep >= 0 ? raw.substring(sep + 4) : raw;

      } finally {
        await sub.cancel();
        sock.destroy();
      }

    } catch (_) {
      // SOCKS5 недоступен (AWG-режим) или соединение не удалось →
      // фоллбэк: системный HTTP (WinHTTP).
      // AWG /installtunnelservice пишет маршруты прямо в ядро через WinTUN,
      // поэтому WinHTTP тоже идёт через VPN-туннель (в отличие от xray/naive).
      final url  = Uri.parse(
          'http://$host:$remotePort/json/?fields=query,country,countryCode');
      final resp = await http.get(url).timeout(const Duration(seconds: 8));
      return resp.body;
    }
  }

  String _extract(String json, String key) {
    final re = RegExp('"$key"\\s*:\\s*"([^"]*)"');
    return re.firstMatch(json)?.group(1) ?? '';
  }

  // Цвет пинга: зелёный <100, жёлтый <250, красный ≥250
  Color _rttColor(int ms) {
    if (ms < 100) return const Color(0xFF00D26A);
    if (ms < 250) return const Color(0xFFFFB800);
    return const Color(0xFFFF4D6D);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 32),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: (_isRu ? const Color(0xFFFF4D6D) : const Color(0xFF00D26A))
              .withValues(alpha: 0.25),
        ),
      ),
      child: _loading
          ? Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const SizedBox(
                  width: 12, height: 12,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.5,
                    color: Color(0xFF4F8EF7),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  'Проверяю IP…',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.4),
                    fontSize: 12,
                  ),
                ),
              ],
            )
          : Row(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Icon(
                  _isRu ? Icons.warning_amber_rounded : Icons.verified_rounded,
                  size: 15,
                  color: _isRu ? const Color(0xFFFF4D6D) : const Color(0xFF00D26A),
                ),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    _isRu
                        ? '⚠️ $_ip ($_country) — трафик не через VPN!'
                        : 'IP: $_ip  •  $_country',
                    style: TextStyle(
                      color: _isRu
                          ? const Color(0xFFFF4D6D)
                          : Colors.white.withValues(alpha: 0.7),
                      fontSize: 12,
                      fontWeight: _isRu ? FontWeight.w600 : FontWeight.w400,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ),
                if (_rttMs != null) ...[
                  const SizedBox(width: 8),
                  Text(
                    '${_rttMs} ms',
                    style: TextStyle(
                      color: _rttColor(_rttMs!),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const SizedBox(width: 6),
                GestureDetector(
                  onTap: () {
                    if (_ip != null && _ip != '—') {
                      Clipboard.setData(ClipboardData(text: _ip!));
                    }
                  },
                  child: Icon(
                    Icons.copy_rounded,
                    size: 13,
                    color: Colors.white.withValues(alpha: 0.2),
                  ),
                ),
                const SizedBox(width: 4),
                GestureDetector(
                  onTap: _checkIp,
                  child: Icon(
                    Icons.refresh_rounded,
                    size: 13,
                    color: Colors.white.withValues(alpha: 0.2),
                  ),
                ),
              ],
            ),
    );
  }
}
