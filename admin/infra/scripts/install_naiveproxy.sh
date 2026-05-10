#!/bin/bash
# ============================================================
# Install NaiveProxy via Caddy with forward_proxy plugin
# Usage: bash install_naiveproxy.sh <DOMAIN> <PASSWORD> [PORT]
# ============================================================
set -euo pipefail

DOMAIN=${1:?"Usage: $0 <domain> <password> [port]"}
PASSWORD=${2:?"Usage: $0 <domain> <password> [port]"}
PORT=${3:-8443}

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERR ]${NC} $1"; }

[[ $EUID -ne 0 ]] && { log_error "Run as root"; exit 1; }

log_info "Installing dependencies..."
apt-get update -qq
apt-get install -y -qq golang-go curl

# Install xcaddy
log_info "Installing xcaddy..."
go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest
export PATH=$PATH:/root/go/bin

# Build Caddy with forward_proxy
log_info "Building Caddy with forward_proxy plugin (this takes a few minutes)..."
xcaddy build --with github.com/klzgrad/forwardproxy@latest --output /usr/local/bin/caddy
chmod +x /usr/local/bin/caddy

# Get SSL cert
log_info "Obtaining SSL certificate for $DOMAIN..."
apt-get install -y -qq certbot
# Stop any process on 80
fuser -k 80/tcp 2>/dev/null || true
certbot certonly --standalone --agree-tos --no-eff-email \
    -m admin@${DOMAIN} -d ${DOMAIN} --non-interactive --quiet

mkdir -p /etc/ssl/naive
cp /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/ssl/naive/cert.pem
cp /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/ssl/naive/key.pem

# Caddyfile
mkdir -p /etc/caddy
cat > /etc/caddy/Caddyfile << CADDY_EOF
{
  servers {
    protocol {
      experimental_http3
    }
  }
}

:${PORT}, ${DOMAIN}:${PORT} {
  tls /etc/ssl/naive/cert.pem /etc/ssl/naive/key.pem
  route {
    forward_proxy {
      basic_auth admin ${PASSWORD}
      hide_ip
      hide_via
      probe_resistance
    }
    respond 404
  }
}
CADDY_EOF

# systemd service
cat > /etc/systemd/system/caddy-naive.service << 'SERVICE_EOF'
[Unit]
Description=Caddy NaiveProxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=root
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
LimitNOFILE=1048576
PrivateTmp=true
ProtectSystem=full
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable caddy-naive
systemctl restart caddy-naive

sleep 2
if systemctl is-active --quiet caddy-naive; then
    log_info "NaiveProxy is running on port $PORT"
    echo ""
    echo "Client config:"
    echo "  Proxy: https://admin:${PASSWORD}@${DOMAIN}:${PORT}"
else
    log_error "caddy-naive failed"
    journalctl -u caddy-naive -n 20 --no-pager
    exit 1
fi
