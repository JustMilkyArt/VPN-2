#!/bin/bash
# ============================================================
# Install Trojan via Xray-core
# Usage: bash install_trojan.sh <PORT> <PASSWORD> <DOMAIN>
# ============================================================
set -euo pipefail

PORT=${1:-10443}
PASSWORD=${2:-$(openssl rand -hex 16)}
DOMAIN=${3:-""}

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERR ]${NC} $1"; }

[[ $EUID -ne 0 ]] && { log_error "Run as root"; exit 1; }

# Ensure Xray is installed
if ! command -v xray &>/dev/null; then
    log_info "Installing Xray-core first..."
    bash <(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install
fi

# SSL certificates
mkdir -p /etc/ssl/xray

if [[ -n "$DOMAIN" ]]; then
    log_info "Obtaining SSL certificate for $DOMAIN..."
    apt-get install -y -qq certbot
    fuser -k 80/tcp 2>/dev/null || true
    certbot certonly --standalone --agree-tos --no-eff-email \
        -m admin@${DOMAIN} -d ${DOMAIN} --non-interactive --quiet || true
    
    if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
        cp /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/ssl/xray/cert.pem
        cp /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/ssl/xray/key.pem
        log_info "Let's Encrypt cert installed"
    else
        log_info "Fallback: self-signed cert"
        openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
            -keyout /etc/ssl/xray/key.pem -out /etc/ssl/xray/cert.pem \
            -subj "/CN=${DOMAIN}" 2>/dev/null
    fi
else
    log_info "No domain, generating self-signed cert..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/xray/key.pem -out /etc/ssl/xray/cert.pem \
        -subj "/CN=localhost" 2>/dev/null
fi

chmod 644 /etc/ssl/xray/cert.pem
chmod 600 /etc/ssl/xray/key.pem

log_info "Configuring Trojan on port $PORT..."

cat > /usr/local/etc/xray/config.json << XRAY_EOF
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [
    {
      "tag": "trojan-in-${PORT}",
      "listen": "0.0.0.0",
      "port": ${PORT},
      "protocol": "trojan",
      "settings": {
        "clients": [{"password": "${PASSWORD}"}]
      },
      "streamSettings": {
        "network": "tcp",
        "security": "tls",
        "tlsSettings": {
          "certificates": [
            {
              "certificateFile": "/etc/ssl/xray/cert.pem",
              "keyFile": "/etc/ssl/xray/key.pem"
            }
          ]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls"]
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

mkdir -p /var/log/xray
systemctl daemon-reload
systemctl enable xray
systemctl restart xray

sleep 2
if systemctl is-active --quiet xray; then
    log_info "Trojan (via Xray) is running on port $PORT"
    echo ""
    echo "=================================="
    echo "CLIENT CONNECTION:"
    SNI=${DOMAIN:-"your-server-ip"}
    echo "trojan://${PASSWORD}@${SNI}:${PORT}?sni=${SNI}&security=tls#Trojan-${PORT}"
    echo "=================================="
else
    log_error "Xray failed to start"
    journalctl -u xray -n 20 --no-pager
    exit 1
fi
