#!/bin/bash
# ============================================================
# Setup Cloudflare WARP as fallback outbound
# Usage: bash setup_warp.sh [PROXY_PORT]
# ============================================================
set -euo pipefail

PROXY_PORT=${1:-40000}

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERR ]${NC} $1"; }

[[ $EUID -ne 0 ]] && { log_error "Run as root"; exit 1; }

log_info "Installing Cloudflare WARP..."

# Add Cloudflare repo
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | \
    gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] \
    https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/cloudflare-client.list

apt-get update -qq
apt-get install -y -qq cloudflare-warp

systemctl enable warp-svc
systemctl start warp-svc
sleep 3

# Register
log_info "Registering WARP..."
warp-cli --accept-tos registration new || true
sleep 2

# Set proxy mode
warp-cli --accept-tos mode proxy
sleep 1

# Set proxy port
warp-cli --accept-tos proxy port ${PROXY_PORT}
sleep 1

# Connect
warp-cli --accept-tos connect
sleep 3

STATUS=$(warp-cli --accept-tos status 2>/dev/null || echo "unknown")
log_info "WARP status: $STATUS"

echo ""
echo "WARP SOCKS5 proxy: 127.0.0.1:${PROXY_PORT}"
echo ""
echo "Add to Xray outbounds:"
cat << XRAY_EOF
{
  "tag": "warp-fallback",
  "protocol": "socks",
  "settings": {
    "servers": [{"address": "127.0.0.1", "port": ${PROXY_PORT}}]
  }
}
XRAY_EOF
