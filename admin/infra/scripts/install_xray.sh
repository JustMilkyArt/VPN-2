#!/bin/bash
# ============================================================
# Install Xray-core on Ubuntu 22.04/24.04
# Usage: bash install_xray.sh
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERR ]${NC} $1"; }

# Root check
[[ $EUID -ne 0 ]] && { log_error "Run as root"; exit 1; }

log_info "Updating system..."
apt-get update -qq
apt-get install -y -qq curl wget unzip

log_info "Installing Xray-core via official script..."
bash <(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install

# Directories
mkdir -p /usr/local/etc/xray
mkdir -p /var/log/xray
chmod 755 /var/log/xray

# Minimal working config
cat > /usr/local/etc/xray/config.json << 'XRAY_CONFIG'
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [],
  "outbounds": [
    {
      "tag": "direct",
      "protocol": "freedom",
      "settings": {}
    }
  ]
}
XRAY_CONFIG

# Enable and start
systemctl daemon-reload
systemctl enable xray
systemctl restart xray

sleep 2
if systemctl is-active --quiet xray; then
    log_info "Xray-core is running"
    xray version
else
    log_error "Xray-core failed to start"
    journalctl -u xray -n 20 --no-pager
    exit 1
fi

# Generate Reality keypair and display
log_info "Generating Reality X25519 keypair..."
xray x25519
