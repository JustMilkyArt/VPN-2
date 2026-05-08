// HomeScreen — main app window

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
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
    try {
      // Import window_manager dynamically to avoid web issues
      final wm = await _getWindowManager();
      if (wm != null) {
        await wm.hide();
      }
    } catch (_) {}
  }

  Future<dynamic> _getWindowManager() async {
    try {
      // window_manager is Windows-only
      return null; // handled in main.dart
    } catch (_) {
      return null;
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
      // Show UAC warning dialog first
      showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => const _UacWarningDialog(),
      ).then((confirmed) {
        if (confirmed == true) {
          prov.connect();
        }
      });
    }
  }
}

// ── UAC Warning dialog ────────────────────────────────────────────────────────

class _UacWarningDialog extends StatelessWidget {
  const _UacWarningDialog();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF1A1D27),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
      ),
      title: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: const Color(0xFFFF8A00).withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(
              Icons.admin_panel_settings_rounded,
              color: Color(0xFFFF8A00),
              size: 22,
            ),
          ),
          const SizedBox(width: 12),
          const Text(
            'Права администратора',
            style: TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Для установки VPN-соединения приложение запросит права администратора Windows.',
            style: TextStyle(
              color: Color(0xFFB0B3C6),
              fontSize: 14,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.04),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: Colors.white.withValues(alpha: 0.06),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.info_outline_rounded,
                  size: 16,
                  color: Colors.white.withValues(alpha: 0.4),
                ),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Появится системное окно Windows с запросом — нажмите «Да».',
                    style: TextStyle(
                      color: Color(0xFF888CA4),
                      fontSize: 12,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: Text(
            'Отмена',
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5),
            ),
          ),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFF4F8EF7),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(9),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
          ),
          child: const Text(
            'Продолжить',
            style: TextStyle(
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
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
      VpnStatus.connected    => ('Защищено', const Color(0xFF00D26A)),
      VpnStatus.connecting   => ('Устанавливается соединение…', const Color(0xFF7B61FF)),
      VpnStatus.disconnecting => ('Отключение…', const Color(0xFFFF8A00)),
      VpnStatus.error        => (error ?? 'Ошибка подключения', const Color(0xFFFF4D6D)),
      VpnStatus.disconnected => ('Не защищено', Colors.white38),
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
