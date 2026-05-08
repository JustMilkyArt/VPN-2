#!/bin/bash
# ============================================================
# Restart all VPN services on a server
# Usage: bash restart_services.sh
# ============================================================
set -uo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[OK ]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[SKIP]${NC} $1"; }

restart_if_active() {
    local svc=$1
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        systemctl restart "$svc" && log_info "Restarted $svc" || log_warn "Failed $svc"
    else
        log_warn "$svc not enabled, skipping"
    fi
}

echo "Restarting VPN services..."
restart_if_active xray
restart_if_active caddy-naive
restart_if_active warp-svc

echo ""
echo "Service status:"
for svc in xray caddy-naive warp-svc; do
    status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    echo "  $svc: $status"
done
