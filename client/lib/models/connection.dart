// Connection model — mirrors the backend /api/v1/client/connections payload

enum Protocol {
  vlessReality,
  amneziaWg,
  naiveProxy,
  trojan,
  unknown,
}

enum ConnectionType {
  direct,
  cascade,
}

enum VpnStatus {
  disconnected,
  connecting,
  connected,
  disconnecting,
  error,
}

class VpnConnection {
  final int id;
  final String name;
  final Protocol protocol;
  final String protoLabel;
  final ConnectionType connType;
  final int port;
  final String serverIp;
  final String serverName;
  final String serverCountry;

  // Client link (URI string)
  final String? clientLink;
  // Full config text (xray JSON or AWG .conf)
  final String? configJson;

  // VLESS + Reality
  final String? uuid;
  final String? realityPublicKey;
  final String? realityShortId;
  final String? realityServerName;

  // AmneziaWG
  final String? wgPublicKey;
  final String? wgClientPrivateKey;
  final String? wgClientPublicKey;
  final String? wgPresharedKey;
  final String? wgClientIp;
  final int? awgJunkPacketCount;
  final int? awgJunkPacketMinSize;
  final int? awgJunkPacketMaxSize;

  // NaiveProxy / Trojan
  final String? password;

  const VpnConnection({
    required this.id,
    required this.name,
    required this.protocol,
    required this.protoLabel,
    required this.connType,
    required this.port,
    required this.serverIp,
    required this.serverName,
    required this.serverCountry,
    this.clientLink,
    this.configJson,
    this.uuid,
    this.realityPublicKey,
    this.realityShortId,
    this.realityServerName,
    this.wgPublicKey,
    this.wgClientPrivateKey,
    this.wgClientPublicKey,
    this.wgPresharedKey,
    this.wgClientIp,
    this.awgJunkPacketCount,
    this.awgJunkPacketMinSize,
    this.awgJunkPacketMaxSize,
    this.password,
  });

  static Protocol _parseProtocol(String? raw) {
    switch (raw) {
      case 'vless_reality':
        return Protocol.vlessReality;
      case 'amnezia_wg':
        return Protocol.amneziaWg;
      case 'naive_proxy':
        return Protocol.naiveProxy;
      case 'trojan':
        return Protocol.trojan;
      default:
        return Protocol.unknown;
    }
  }

  factory VpnConnection.fromJson(Map<String, dynamic> j) {
    return VpnConnection(
      id: j['id'] as int,
      name: j['name'] as String? ?? 'Connection ${j['id']}',
      protocol: _parseProtocol(j['protocol'] as String?),
      protoLabel: j['proto_label'] as String? ?? j['protocol'] as String? ?? '?',
      connType: (j['conn_type'] as String?) == 'cascade'
          ? ConnectionType.cascade
          : ConnectionType.direct,
      port: j['port'] as int? ?? 443,
      serverIp: j['server_ip'] as String? ?? '',
      serverName: j['server_name'] as String? ?? '',
      serverCountry: j['server_country'] as String? ?? '??',
      clientLink: j['client_link'] as String?,
      configJson: j['config_json'] as String?,
      uuid: j['uuid'] as String?,
      realityPublicKey: j['reality_public_key'] as String?,
      realityShortId: j['reality_short_id'] as String?,
      realityServerName: j['reality_server_name'] as String?,
      wgPublicKey: j['wg_public_key'] as String?,
      wgClientPrivateKey: j['wg_client_private_key'] as String?,
      wgClientPublicKey: j['wg_client_public_key'] as String?,
      wgPresharedKey: j['wg_preshared_key'] as String?,
      wgClientIp: j['wg_client_ip'] as String?,
      awgJunkPacketCount: j['awg_junk_packet_count'] as int?,
      awgJunkPacketMinSize: j['awg_junk_packet_min_size'] as int?,
      awgJunkPacketMaxSize: j['awg_junk_packet_max_size'] as int?,
      password: j['password'] as String?,
    );
  }

  // Country flag emoji from 2-letter country code
  String get countryFlag {
    final upper = serverCountry.toUpperCase();
    if (upper.length != 2) return '🌐';
    final a = upper.codeUnitAt(0) - 65 + 0x1F1E6;
    final b = upper.codeUnitAt(1) - 65 + 0x1F1E6;
    return String.fromCharCode(a) + String.fromCharCode(b);
  }

  String get typeLabel =>
      connType == ConnectionType.cascade ? 'Каскад' : 'Прямое';
}
