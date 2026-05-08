// App-wide constants

class AppConstants {
  AppConstants._();

  // Backend base URL
  static const String backendUrl = 'https://admin.milkyims.com';

  // Client API key — must match CLIENT_API_KEY in server .env
  // Generated: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  static const String clientApiKey = 'MilkyVPN-2025-xK9mP3nQ7rL5vW1jY8tA4bZ6dF0hE2';

  // API endpoints
  static const String connectionsEndpoint = '/api/v1/client/connections';
  static const String healthEndpoint = '/api/v1/client/health';

  // Timeouts
  static const Duration connectTimeout = Duration(seconds: 15);
  static const Duration requestTimeout = Duration(seconds: 20);

  // Cache TTL (how long to use cached connections when offline)
  static const Duration cacheTtl = Duration(hours: 24);

  // App metadata
  static const String appName = 'MilkyVPN';
  static const String appVersion = '1.0.0';

  // VPN engine binary names (bundled in assets/engines/ and extracted to appDir)
  static const String xrayExe = 'xray.exe';
  static const String naiveExe = 'naive.exe';
  static const String awgExe = 'awg-quick.exe'; // AmneziaWG CLI

  // Temp config file names (written to temp dir before launching engine)
  static const String xrayConfigFile = 'xray_config.json';
  static const String awgConfigFile = 'wg0.conf';
  static const String naiveConfigFile = 'naive_config.json';

  // Xray TUN interface name
  static const String xrayTunName = 'tun0';

  // Local SOCKS proxy port used by xray for routing
  static const int xraySocksPort = 10808;

  // SharedPreferences keys
  static const String prefCachedConnections = 'cached_connections';
  static const String prefLastSelectedId = 'last_selected_id';
  static const String prefCacheTimestamp = 'cache_timestamp';
}
