// ConnectButton — animated main action button

import 'package:flutter/material.dart';
import '../models/connection.dart';

class ConnectButton extends StatefulWidget {
  final VpnStatus status;
  final VoidCallback? onPressed;

  const ConnectButton({
    super.key,
    required this.status,
    this.onPressed,
  });

  @override
  State<ConnectButton> createState() => _ConnectButtonState();
}

class _ConnectButtonState extends State<ConnectButton>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _scale = Tween(begin: 1.0, end: 1.08).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
    if (widget.status == VpnStatus.connecting ||
        widget.status == VpnStatus.disconnecting) {
      _ctrl.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(ConnectButton old) {
    super.didUpdateWidget(old);
    if (widget.status == VpnStatus.connecting ||
        widget.status == VpnStatus.disconnecting) {
      if (!_ctrl.isAnimating) _ctrl.repeat(reverse: true);
    } else {
      _ctrl.stop();
      _ctrl.reset();
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final (label, gradient, shadow) = _appearance(widget.status);
    final enabled = widget.status == VpnStatus.connected ||
        widget.status == VpnStatus.disconnected ||
        widget.status == VpnStatus.error;

    return AnimatedBuilder(
      animation: _scale,
      builder: (_, child) => Transform.scale(
        scale: _ctrl.isAnimating ? _scale.value : 1.0,
        child: child,
      ),
      child: GestureDetector(
        onTap: enabled ? widget.onPressed : null,
        child: Container(
          width: 180,
          height: 180,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: enabled
                ? gradient
                : LinearGradient(
                    colors: [Colors.grey.shade800, Colors.grey.shade700],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
            boxShadow: enabled
                ? shadow
                : [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.4),
                      blurRadius: 20,
                    )
                  ],
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildIcon(widget.status),
              const SizedBox(height: 10),
              Text(
                label,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildIcon(VpnStatus status) {
    if (status == VpnStatus.connecting || status == VpnStatus.disconnecting) {
      return const SizedBox(
        width: 36,
        height: 36,
        child: CircularProgressIndicator(
          color: Colors.white,
          strokeWidth: 3,
        ),
      );
    }
    final iconData = status == VpnStatus.connected
        ? Icons.shield_rounded
        : Icons.shield_outlined;
    return Icon(iconData, size: 52, color: Colors.white);
  }

  (String, LinearGradient, List<BoxShadow>) _appearance(VpnStatus status) {
    switch (status) {
      case VpnStatus.connected:
        return (
          'Отключить',
          const LinearGradient(
            colors: [Color(0xFF00C96A), Color(0xFF00A855)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          [
            BoxShadow(
              color: const Color(0xFF00D26A).withValues(alpha: 0.45),
              blurRadius: 35,
              spreadRadius: 5,
            ),
          ],
        );
      case VpnStatus.connecting:
        return (
          'Подключение',
          const LinearGradient(
            colors: [Color(0xFF7B61FF), Color(0xFF5B3FDD)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          [
            BoxShadow(
              color: const Color(0xFF7B61FF).withValues(alpha: 0.4),
              blurRadius: 30,
              spreadRadius: 3,
            ),
          ],
        );
      case VpnStatus.disconnecting:
        return (
          'Отключение',
          const LinearGradient(
            colors: [Color(0xFFFF8A00), Color(0xFFE06000)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          [
            BoxShadow(
              color: const Color(0xFFFF8A00).withValues(alpha: 0.35),
              blurRadius: 28,
            ),
          ],
        );
      case VpnStatus.error:
        return (
          'Повторить',
          const LinearGradient(
            colors: [Color(0xFFFF4D6D), Color(0xFFCC2244)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          [
            BoxShadow(
              color: const Color(0xFFFF4D6D).withValues(alpha: 0.35),
              blurRadius: 28,
            ),
          ],
        );
      default:
        return (
          'Подключить',
          const LinearGradient(
            colors: [Color(0xFF4F8EF7), Color(0xFF2563EB)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          [
            BoxShadow(
              color: const Color(0xFF4F8EF7).withValues(alpha: 0.4),
              blurRadius: 30,
              spreadRadius: 3,
            ),
          ],
        );
    }
  }
}
