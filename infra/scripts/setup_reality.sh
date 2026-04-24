#!/bin/bash
# ============================================================
# Setup VLESS + Reality on Xray
# Usage: bash setup_reality.sh <PORT> <UUID> <PRIVATE_KEY> <PUBLIC_KEY> <SHORT_ID> [SNI]
# ============================================================
set -euo pipefail

PORT=${1:-10443}
UUID=${2:-$(cat /proc/sys/kernel/random/uuid)}
PRIVATE_KEY=${3:-""}
PUBLIC_KEY=${4:-""}
SHORT_ID=${5:-$(openssl rand -hex 8)}
SNI=${6:-"www.microsoft.com"}

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }

[[ $EUID -ne 0 ]] && { echo "Run as root"; exit 1; }

# Generate keys if not provided
if [[ -z "$PRIVATE_KEY" || -z "$PUBLIC_KEY" ]]; then
    log_info "Generating X25519 keypair..."
    KEYS=$(xray x25519)
    PRIVATE_KEY=$(echo "$KEYS" | grep "Private" | awk '{print $3}')
    PUBLIC_KEY=$(echo "$KEYS" | grep "Public" | awk '{print $3}')
fi

log_info "Configuring VLESS+Reality:"
echo "  Port: $PORT"
echo "  UUID: $UUID"
echo "  SNI:  $SNI"
echo "  Short ID: $SHORT_ID"

cat > /usr/local/etc/xray/config.json << XRAY_EOF
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [
    {
      "tag": "vless-in-${PORT}",
      "listen": "0.0.0.0",
      "port": ${PORT},
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "${UUID}",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "${SNI}:443",
          "xver": 0,
          "serverNames": ["${SNI}"],
          "privateKey": "${PRIVATE_KEY}",
          "shortIds": ["${SHORT_ID}"],
          "fingerprint": "chrome"
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {
      "tag": "direct",
      "protocol": "freedom",
      "settings": {}
    }
  ]
}
XRAY_EOF

systemctl reload xray || systemctl restart xray
sleep 1

if systemctl is-active --quiet xray; then
    log_info "Xray VLESS+Reality configured successfully"
    echo ""
    echo "=========================================="
    echo "CLIENT CONNECTION STRING:"
    echo "vless://${UUID}@SERVER_IP:${PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${SNI}&fp=chrome&pbk=${PUBLIC_KEY}&sid=${SHORT_ID}&type=tcp#Reality-${PORT}"
    echo "=========================================="
else
    echo "Xray failed to start"
    journalctl -u xray -n 20 --no-pager
    exit 1
fi
