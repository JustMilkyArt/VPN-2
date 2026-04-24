#!/bin/bash
# ============================================================
# sync_docs_password.sh
#
# Синхронизирует пароль /docs с ADMIN_PASSWORD из .env
# Вызывается автоматически через ExecStartPre в systemd юните
# при каждом старте/рестарте vpn-admin-backend.
#
# При смене пароля в .env достаточно:
#   systemctl restart vpn-admin-backend
# ============================================================

ENV_FILE="/opt/vpn-admin/backend/.env"
HTPASSWD_FILE="/etc/nginx/docs.htpasswd"

if [ ! -f "$ENV_FILE" ]; then
    echo "[sync_docs_password] ERROR: .env not found at $ENV_FILE"
    exit 1
fi

# Читаем логин и пароль из .env
ADMIN_USER=$(grep -E '^ADMIN_USERNAME=' "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
ADMIN_PASS=$(grep -E '^ADMIN_PASSWORD=' "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'")

if [ -z "$ADMIN_USER" ] || [ -z "$ADMIN_PASS" ]; then
    echo "[sync_docs_password] ERROR: Could not read credentials from .env"
    exit 1
fi

# Пересоздаём .htpasswd (bcrypt хэш, -B флаг)
htpasswd -cbB "$HTPASSWD_FILE" "$ADMIN_USER" "$ADMIN_PASS"
chmod 640 "$HTPASSWD_FILE"
chown root:www-data "$HTPASSWD_FILE"

echo "[sync_docs_password] OK: credentials synced for user '$ADMIN_USER'"

# Перезагружаем nginx чтобы подхватил новый htpasswd
nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
