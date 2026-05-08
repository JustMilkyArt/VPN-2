#!/usr/bin/env bash
# ============================================================
#  reset_creator_2fa.sh  —  SSH-side Creator recovery tool
#  Run as root on the admin server when Creator is locked out
#  of TOTP (lost phone etc.).
#
#  Effect:
#    • Clears Creator's TOTP secret
#    • Sets totp_enabled = 0
#    • Sets force_change_creds = 1  (must re-bind on next login)
#    • Does NOT touch the password
#
#  Usage:
#    sudo bash /opt/vpn-admin/infra/scripts/reset_creator_2fa.sh
# ============================================================

set -euo pipefail

DB_PATH="${VPN_DB_PATH:-/opt/vpn-admin/vpn_admin.db}"
LOG_FILE="/var/log/vpn-admin/reset_creator_2fa.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[${TIMESTAMP}]${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" | tee -a "$LOG_FILE"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG_FILE"; exit 1; }

# ── Guards ────────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && err "Must be run as root"
[[ ! -f "$DB_PATH" ]] && err "Database not found: $DB_PATH"
command -v sqlite3 >/dev/null 2>&1 || apt-get install -y sqlite3 >/dev/null

mkdir -p "$(dirname "$LOG_FILE")"

log "=== Creator 2FA reset started ==="
log "Database: $DB_PATH"

# ── Find Creator ──────────────────────────────────────────────────────────────
CREATOR_ROW=$(sqlite3 "$DB_PATH" "SELECT id, username FROM admin_users WHERE role='creator' LIMIT 1;")
[[ -z "$CREATOR_ROW" ]] && err "No Creator account found in database"

CREATOR_ID=$(echo "$CREATOR_ROW" | cut -d'|' -f1)
CREATOR_NAME=$(echo "$CREATOR_ROW" | cut -d'|' -f2)

log "Found Creator: id=${CREATOR_ID}, username=${CREATOR_NAME}"

# ── Confirmation prompt ───────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}WARNING: This will disable TOTP for Creator account '${CREATOR_NAME}'.${NC}"
echo -e "${YELLOW}Creator will be able to log in with password only until new TOTP is set up.${NC}"
echo ""
read -r -p "Type 'RESET' to confirm: " CONFIRM
[[ "$CONFIRM" != "RESET" ]] && { warn "Aborted by user"; exit 0; }

# ── Apply reset ───────────────────────────────────────────────────────────────
sqlite3 "$DB_PATH" <<SQL
UPDATE admin_users
SET
    totp_secret        = NULL,
    totp_enabled       = 0,
    force_change_creds = 1,
    updated_at         = CURRENT_TIMESTAMP
WHERE id = ${CREATOR_ID};
SQL

# Verify
RESULT=$(sqlite3 "$DB_PATH" "SELECT totp_enabled, force_change_creds FROM admin_users WHERE id=${CREATOR_ID};")
TOTP_EN=$(echo "$RESULT" | cut -d'|' -f1)
FORCE_CH=$(echo "$RESULT" | cut -d'|' -f2)

[[ "$TOTP_EN" == "0" && "$FORCE_CH" == "1" ]] || err "Reset verification failed: $RESULT"

log "TOTP disabled for Creator '${CREATOR_NAME}'"
log "force_change_creds=1 — Creator must re-bind TOTP on next login"

# ── Restart backend so session cache is cleared ───────────────────────────────
if systemctl is-active --quiet vpn-admin-backend 2>/dev/null; then
    systemctl restart vpn-admin-backend
    log "vpn-admin-backend restarted"
fi

echo ""
echo -e "${GREEN}✓ Recovery complete.${NC}"
echo -e "  Creator can now log in with password only."
echo -e "  On first login they will be required to re-bind the Authenticator."
echo ""
log "=== Reset finished ==="
