// ConnectionCard — one item in the connections list

import 'package:flutter/material.dart';
import '../models/connection.dart';

class ConnectionCard extends StatelessWidget {
  final VpnConnection connection;
  final bool isSelected;
  final bool isActiveVpn; // this connection is the one currently running VPN
  final VoidCallback onTap;

  const ConnectionCard({
    super.key,
    required this.connection,
    required this.isSelected,
    required this.isActiveVpn,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;

    Color borderColor;
    Color bgColor;
    if (isActiveVpn) {
      borderColor = const Color(0xFF00D26A);
      bgColor = const Color(0xFF00D26A).withValues(alpha: 0.08);
    } else if (isSelected) {
      borderColor = colors.primary;
      bgColor = colors.primary.withValues(alpha: 0.07);
    } else {
      borderColor = Colors.white.withValues(alpha: 0.06);
      bgColor = Colors.white.withValues(alpha: 0.03);
    }

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: borderColor, width: isSelected || isActiveVpn ? 1.5 : 1),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              // Country flag + protocol icon column
              _ProtocolBadge(protocol: connection.protocol),
              const SizedBox(width: 14),
              // Name + meta
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      connection.name,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        letterSpacing: -0.2,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Text(
                          connection.countryFlag,
                          style: const TextStyle(fontSize: 13),
                        ),
                        const SizedBox(width: 5),
                        Text(
                          connection.serverCountry,
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.5),
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(width: 8),
                        _TypeChip(type: connection.connType),
                      ],
                    ),
                  ],
                ),
              ),
              // Status indicator
              if (isActiveVpn)
                _StatusDot(color: const Color(0xFF00D26A), pulse: true)
              else if (isSelected)
                _StatusDot(color: colors.primary, pulse: false)
              else
                const SizedBox(width: 10),
            ],
          ),
        ),
      ),
    );
  }
}

class _ProtocolBadge extends StatelessWidget {
  final Protocol protocol;
  const _ProtocolBadge({required this.protocol});

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (protocol) {
      Protocol.vlessReality => ('VR', const Color(0xFF7B61FF)),
      Protocol.amneziaWg    => ('WG', const Color(0xFF00C2FF)),
      Protocol.naiveProxy   => ('NP', const Color(0xFFFF8A00)),
      Protocol.trojan        => ('TR', const Color(0xFFFF4D6D)),
      Protocol.unknown       => ('??', Colors.grey),
    };

    return Container(
      width: 42,
      height: 42,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      alignment: Alignment.center,
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

class _TypeChip extends StatelessWidget {
  final ConnectionType type;
  const _TypeChip({required this.type});

  @override
  Widget build(BuildContext context) {
    final isCascade = type == ConnectionType.cascade;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: isCascade
            ? const Color(0xFFFF8A00).withValues(alpha: 0.15)
            : const Color(0xFF00D26A).withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(5),
      ),
      child: Text(
        isCascade ? 'КАСКАД' : 'ПРЯМОЕ',
        style: TextStyle(
          color: isCascade
              ? const Color(0xFFFF8A00)
              : const Color(0xFF00D26A),
          fontSize: 10,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.8,
        ),
      ),
    );
  }
}

class _StatusDot extends StatefulWidget {
  final Color color;
  final bool pulse;
  const _StatusDot({required this.color, required this.pulse});

  @override
  State<_StatusDot> createState() => _StatusDotState();
}

class _StatusDotState extends State<_StatusDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    );
    _anim = Tween(begin: 0.4, end: 1.0).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
    if (widget.pulse) {
      _ctrl.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.pulse) {
      return Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(
          color: widget.color,
          shape: BoxShape.circle,
        ),
      );
    }
    return AnimatedBuilder(
      animation: _anim,
      builder: (_, __) => Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(
          color: widget.color.withValues(alpha: _anim.value),
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: widget.color.withValues(alpha: _anim.value * 0.6),
              blurRadius: 6,
              spreadRadius: 2,
            ),
          ],
        ),
      ),
    );
  }
}
