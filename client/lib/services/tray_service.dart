// System tray service — Windows tray icon + context menu

import 'package:flutter/foundation.dart';
import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';
import '../models/connection.dart';

class TrayService with TrayListener {
  TrayService._();
  static final TrayService instance = TrayService._();

  VoidCallback? onShowWindow;
  VoidCallback? onConnectToggle;
  VoidCallback? onQuit;

  Future<void> init() async {
    trayManager.addListener(this);
    await _setIcon(VpnStatus.disconnected);
    await _buildMenu(VpnStatus.disconnected, null);
  }

  Future<void> updateStatus(VpnStatus status, String? connName) async {
    await _setIcon(status);
    await _buildMenu(status, connName);
  }

  Future<void> _setIcon(VpnStatus status) async {
    // Use bundled PNG icons — grey=disconnected, green=connected, yellow=connecting
    String iconAsset;
    switch (status) {
      case VpnStatus.connected:
        iconAsset = 'assets/icons/tray_connected.ico';
        break;
      case VpnStatus.connecting:
      case VpnStatus.disconnecting:
        iconAsset = 'assets/icons/tray_connecting.ico';
        break;
      default:
        iconAsset = 'assets/icons/tray_disconnected.ico';
    }
    await trayManager.setIcon(iconAsset);
  }

  Future<void> _buildMenu(VpnStatus status, String? connName) async {
    String statusText;
    switch (status) {
      case VpnStatus.connected:
        statusText = 'Подключено: ${connName ?? ''}';
        break;
      case VpnStatus.connecting:
        statusText = 'Подключение…';
        break;
      case VpnStatus.disconnecting:
        statusText = 'Отключение…';
        break;
      case VpnStatus.error:
        statusText = 'Ошибка подключения';
        break;
      default:
        statusText = 'Отключено';
    }

    final menu = Menu(
      items: [
        MenuItem(
          key: 'status',
          label: statusText,
          disabled: true,
        ),
        MenuItem.separator(),
        MenuItem(
          key: 'show',
          label: 'Открыть MilkyVPN',
        ),
        MenuItem(
          key: 'toggle',
          label: status == VpnStatus.connected ? 'Отключиться' : 'Подключиться',
          disabled: status == VpnStatus.connecting ||
              status == VpnStatus.disconnecting,
        ),
        MenuItem.separator(),
        MenuItem(
          key: 'quit',
          label: 'Выйти',
        ),
      ],
    );
    await trayManager.setContextMenu(menu);
    await trayManager.setToolTip(
        'MilkyVPN — $statusText');
  }

  // ── TrayListener ──────────────────────────────────────────────────────────

  @override
  void onTrayIconMouseDown() {
    // Single click — show window
    onShowWindow?.call();
    windowManager.show();
    windowManager.focus();
  }

  @override
  void onTrayIconRightMouseDown() {
    trayManager.popUpContextMenu();
  }

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    switch (menuItem.key) {
      case 'show':
        onShowWindow?.call();
        windowManager.show();
        windowManager.focus();
        break;
      case 'toggle':
        onConnectToggle?.call();
        break;
      case 'quit':
        onQuit?.call();
        break;
    }
  }

  Future<void> dispose() async {
    trayManager.removeListener(this);
    await trayManager.destroy();
  }
}
