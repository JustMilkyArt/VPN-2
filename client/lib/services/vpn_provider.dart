// VPN Provider — central state management (Provider pattern)
// Owns: connection list, selected connection, VPN status

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/connection.dart';
import '../utils/constants.dart';
import 'api_service.dart';
import 'vpn_engine.dart';

enum LoadState { idle, loading, loaded, error }

class VpnProvider extends ChangeNotifier {
  // ── State ─────────────────────────────────────────────────────────────────

  LoadState loadState = LoadState.idle;
  String? loadError;

  List<VpnConnection> connections = [];
  VpnConnection? selectedConnection;

  VpnStatus get vpnStatus => VpnEngine.instance.status.value;
  String? get vpnError => VpnEngine.instance.lastError.value;

  bool get isConnected => vpnStatus == VpnStatus.connected;
  bool get isBusy =>
      vpnStatus == VpnStatus.connecting ||
      vpnStatus == VpnStatus.disconnecting;

  // ── Init ──────────────────────────────────────────────────────────────────

  VpnProvider() {
    VpnEngine.instance.status.addListener(_onEngineStatusChange);
    VpnEngine.instance.lastError.addListener(_onEngineStatusChange);
  }

  @override
  void dispose() {
    VpnEngine.instance.status.removeListener(_onEngineStatusChange);
    VpnEngine.instance.lastError.removeListener(_onEngineStatusChange);
    super.dispose();
  }

  void _onEngineStatusChange() => notifyListeners();

  // ── Load connections ──────────────────────────────────────────────────────

  Future<void> loadConnections({bool forceRefresh = false}) async {
    loadState = LoadState.loading;
    loadError = null;
    notifyListeners();

    try {
      // Try fresh data from backend
      if (forceRefresh) {
        connections = await ApiService.instance.fetchConnections();
      } else {
        // Try cache first for instant display, then refresh in background
        final cached = await ApiService.instance.loadCachedConnections();
        if (cached != null && cached.isNotEmpty) {
          connections = cached;
          loadState = LoadState.loaded;
          notifyListeners();
          // Background refresh
          _refreshInBackground();
        } else {
          connections = await ApiService.instance.fetchConnections();
        }
      }

      await _restoreLastSelected();
      loadState = LoadState.loaded;
    } catch (e) {
      loadError = e.toString().replaceFirst('ApiException: ', '');
      loadState = LoadState.error;
    }

    notifyListeners();
  }

  void _refreshInBackground() {
    ApiService.instance.fetchConnections().then((fresh) {
      connections = fresh;
      _restoreLastSelected();
      notifyListeners();
    }).catchError((_) {
      // Ignore background refresh failures
    });
  }

  // ── Selection ─────────────────────────────────────────────────────────────

  void selectConnection(VpnConnection conn) {
    selectedConnection = conn;
    _saveLastSelected(conn.id);
    notifyListeners();
  }

  Future<void> _restoreLastSelected() async {
    final prefs = await SharedPreferences.getInstance();
    final lastId = prefs.getInt(AppConstants.prefLastSelectedId);
    if (lastId != null) {
      final match = connections.where((c) => c.id == lastId);
      if (match.isNotEmpty) {
        selectedConnection = match.first;
      }
    }
    if (selectedConnection == null && connections.isNotEmpty) {
      selectedConnection = connections.first;
    }
  }

  Future<void> _saveLastSelected(int id) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(AppConstants.prefLastSelectedId, id);
  }

  // ── Connect / Disconnect ──────────────────────────────────────────────────

  Future<void> connect() async {
    if (selectedConnection == null) return;
    if (isBusy) return;

    try {
      await VpnEngine.instance.connect(selectedConnection!);
    } catch (_) {
      // Error already stored in VpnEngine.instance.lastError
      notifyListeners();
    }
  }

  Future<void> disconnect() async {
    if (isBusy) return;
    await VpnEngine.instance.disconnect();
    notifyListeners();
  }

  // ── Protocol helpers ──────────────────────────────────────────────────────

  List<VpnConnection> get directConnections =>
      connections.where((c) => c.connType == ConnectionType.direct).toList();

  List<VpnConnection> get cascadeConnections =>
      connections.where((c) => c.connType == ConnectionType.cascade).toList();

  Map<String, List<VpnConnection>> get groupedByCountry {
    final map = <String, List<VpnConnection>>{};
    for (final c in connections) {
      final key = '${c.countryFlag} ${c.serverCountry}';
      map.putIfAbsent(key, () => []).add(c);
    }
    return map;
  }
}
