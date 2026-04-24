#!/bin/bash
# ============================================================
# Deploy FastAPI backend on Ubuntu 24.04
# Usage: bash deploy_backend.sh [--update]
# Runs on the ADMIN SERVER (not on VPN nodes)
# ============================================================
set -euo pipefail

UPDATE=${1:-""}
APP_DIR="/opt/vpn-admin"
SERVICE_USER="vpnadmin"
PYTHON_BIN="python3"
VENV="$APP_DIR/venv"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERR ]${NC} $1"; }

[[ $EUID -ne 0 ]] && { log_error "Run as root"; exit 1; }

log_info "Deploying VPN Admin Backend..."

# System deps
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl nginx

# Create app user
id "$SERVICE_USER" &>/dev/null || useradd -r -s /bin/bash -d "$APP_DIR" "$SERVICE_USER"

# Create app directory
mkdir -p "$APP_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# Clone or update
if [[ -d "$APP_DIR/.git" ]]; then
    log_info "Updating existing installation..."
    cd "$APP_DIR"
    git pull origin main
else
    log_info "Cloning repository..."
    # Replace with your actual repo URL
    git clone https://github.com/JustMilkyArt/VPN-2.git "$APP_DIR" || {
        log_warn "Git clone failed, assuming files are already here"
    }
fi

cd "$APP_DIR/backend"

# Create virtualenv
log_info "Setting up Python virtualenv..."
$PYTHON_BIN -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt

# Setup .env if not exists
if [[ ! -f "$APP_DIR/backend/.env" ]]; then
    log_warn "No .env found - copying example"
    cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
    
    # Generate random secret key
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s/your-secret-key-change-in-production-min-32-chars/$SECRET/" "$APP_DIR/backend/.env"
    
    log_warn "Please edit $APP_DIR/backend/.env with proper settings!"
fi

# systemd service
cat > /etc/systemd/system/vpn-admin-backend.service << SERVICE_EOF
[Unit]
Description=VPN Admin Backend (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}/backend
Environment=PATH=${VENV}/bin:/usr/bin:/bin
ExecStart=${VENV}/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

systemctl daemon-reload
systemctl enable vpn-admin-backend
systemctl restart vpn-admin-backend

sleep 3
if systemctl is-active --quiet vpn-admin-backend; then
    log_info "Backend is running at http://localhost:8000"
else
    log_error "Backend failed to start"
    journalctl -u vpn-admin-backend -n 30 --no-pager
    exit 1
fi

# Nginx reverse proxy
log_info "Setting up Nginx..."
cat > /etc/nginx/sites-available/vpn-admin << 'NGINX_EOF'
server {
    listen 80;
    server_name _;

    # Frontend (Flutter Web) - served from /opt/vpn-admin/frontend/build/web
    location / {
        root /opt/vpn-admin/frontend/build/web;
        try_files $uri $uri/ /index.html;
    }

    # API proxy to FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
        proxy_set_header Host $host;
    }
}
NGINX_EOF

ln -sf /etc/nginx/sites-available/vpn-admin /etc/nginx/sites-enabled/vpn-admin
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx

log_info "Deployment complete!"
echo ""
echo "  Backend API: http://SERVER_IP:8000"
echo "  API Docs:    http://SERVER_IP:8000/docs"
echo "  Web Admin:   http://SERVER_IP"
echo ""
echo "Default login: admin / changeme123"
echo "CHANGE THE PASSWORD: edit $APP_DIR/backend/.env"
