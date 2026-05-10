// API service — fetches connections from the backend and caches them locally

import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/connection.dart';
import '../utils/constants.dart';

class ApiService {
  ApiService._();
  static final ApiService instance = ApiService._();

  // ── Fetch connections from backend ────────────────────────────────────────

  Future<List<VpnConnection>> fetchConnections() async {
    try {
      final uri = Uri.parse(
          '${AppConstants.backendUrl}${AppConstants.connectionsEndpoint}');
      final response = await http
          .get(uri, headers: {'X-API-Key': AppConstants.clientApiKey})
          .timeout(AppConstants.requestTimeout);

      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body) as List<dynamic>;
        final connections = data
            .map((e) => VpnConnection.fromJson(e as Map<String, dynamic>))
            .toList();
        await _cacheConnections(data);
        return connections;
      } else {
        throw ApiException(
            'Server returned ${response.statusCode}: ${response.body}');
      }
    } on ApiException {
      rethrow;
    } catch (e) {
      // Network error — try cache
      final cached = await _loadCachedConnections();
      if (cached != null) return cached;
      throw ApiException('No network and no cached data: $e');
    }
  }

  // ── Health check ──────────────────────────────────────────────────────────

  Future<bool> checkHealth() async {
    try {
      final uri = Uri.parse(
          '${AppConstants.backendUrl}${AppConstants.healthEndpoint}');
      final response = await http
          .get(uri, headers: {'X-API-Key': AppConstants.clientApiKey})
          .timeout(AppConstants.connectTimeout);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ── Local cache ───────────────────────────────────────────────────────────

  Future<void> _cacheConnections(List<dynamic> raw) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        AppConstants.prefCachedConnections, jsonEncode(raw));
    await prefs.setInt(AppConstants.prefCacheTimestamp,
        DateTime.now().millisecondsSinceEpoch);
  }

  Future<List<VpnConnection>?> _loadCachedConnections() async {
    final prefs = await SharedPreferences.getInstance();
    final json = prefs.getString(AppConstants.prefCachedConnections);
    final ts = prefs.getInt(AppConstants.prefCacheTimestamp) ?? 0;
    if (json == null) return null;

    final age = DateTime.now()
        .difference(DateTime.fromMillisecondsSinceEpoch(ts));
    if (age > AppConstants.cacheTtl) return null;

    final List<dynamic> data = jsonDecode(json) as List<dynamic>;
    return data
        .map((e) => VpnConnection.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<VpnConnection>?> loadCachedConnections() =>
      _loadCachedConnections();
}

class ApiException implements Exception {
  final String message;
  ApiException(this.message);

  @override
  String toString() => 'ApiException: $message';
}
