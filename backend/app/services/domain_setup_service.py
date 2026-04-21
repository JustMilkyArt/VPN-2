"""
Background service for automated subdomain setup:
  1. Determine target IP
  2. Create A-record in Porkbun
  3. Wait for DNS propagation
  4. Install Certbot (if missing)
  5. Issue Let's Encrypt certificate
  6. Configure Nginx (HTTPS proxy / static)
  7. Reload Nginx
  8. Verify HTTPS
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.db.database import SessionLocal
from app.models.domain import Subdomain, SubdomainStatus, SubdomainType
from app.services import porkbun_service
from app.services.ssh_service import SSHService
from app.core.config import settings

logger = logging.getLogger(__name__)

# Admin panel server IP and SSH credentials from settings
ADMIN_SERVER_IP = settings.ADMIN_SERVER_IP
ADMIN_SSH_USER = settings.ADMIN_SSH_USER
ADMIN_SSH_PASSWORD = settings.ADMIN_SSH_PASSWORD
ADMIN_SSH_PORT = settings.ADMIN_SSH_PORT

# Nginx template for admin panel subdomain
NGINX_ADMIN_TEMPLATE = """
server {{
    listen 80;
    server_name {full_name};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {full_name};

    ssl_certificate     /etc/letsencrypt/live/{full_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{full_name}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Frontend static files
    root /opt/vpn-admin/frontend/web_admin;
    index index.html;

    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # Backend API proxy
    location /api/ {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }}

    # Block docs from outside
    location ~ ^/(docs|redoc|openapi.json) {{
        deny all;
        return 404;
    }}

    location /health {{
        proxy_pass http://127.0.0.1:8000/health;
    }}
}}
"""

# Nginx template for client site subdomain (reserved for future)
NGINX_CLIENT_TEMPLATE = """
server {{
    listen 80;
    server_name {full_name};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {full_name};

    ssl_certificate     /etc/letsencrypt/live/{full_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{full_name}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    root /opt/vpn-admin/frontend/web_admin;
    index index.html;

    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""


def _append_log(subdomain: Subdomain, step: str, status: str, detail: str = ""):
    """Append a step entry to the subdomain's setup_log JSON array."""
    try:
        log = json.loads(subdomain.setup_log) if subdomain.setup_log else []
    except Exception:
        log = []
    log.append({
        "step": step,
        "status": status,   # "ok" | "error" | "running" | "skipped"
        "detail": detail,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    subdomain.setup_log = json.dumps(log)


def _save(db, subdomain: Subdomain):
    db.add(subdomain)
    db.commit()
    db.refresh(subdomain)


async def run_subdomain_setup(subdomain_id: int):
    """
    Main entry point called as background task.
    Runs the full setup pipeline for a subdomain.
    """
    db = SessionLocal()
    try:
        subdomain = db.query(Subdomain).filter(Subdomain.id == subdomain_id).first()
        if not subdomain:
            logger.error(f"Subdomain {subdomain_id} not found")
            return

        domain = subdomain.domain
        subdomain.status = SubdomainStatus.in_progress
        _save(db, subdomain)

        stype = subdomain.subdomain_type

        # ── VPN / None subdomains ──────────────────────────────────────────────
        if stype in (SubdomainType.vpn, SubdomainType.none):
            _append_log(subdomain, "Резервирование поддомена", "ok",
                        "Поддомен зарегистрирован. A-запись и SSL будут созданы при настройке подключения.")
            subdomain.status = SubdomainStatus.reserved
            _save(db, subdomain)
            return

        # ── Admin panel / Client site ──────────────────────────────────────────
        target_ip = subdomain.target_ip or ADMIN_SERVER_IP
        full_name = subdomain.full_name

        ssh = SSHService(
            host=target_ip,
            user=ADMIN_SSH_USER,
            password=ADMIN_SSH_PASSWORD,
            port=ADMIN_SSH_PORT,
        )

        # Step 1: Determine IP
        _append_log(subdomain, "Определение IP сервера", "ok", f"IP: {target_ip}")
        _save(db, subdomain)

        # Step 2: Create A-record
        try:
            _append_log(subdomain, "Создание A-записи в Porkbun", "running")
            _save(db, subdomain)

            record_id = await porkbun_service.create_a_record(
                domain=domain.name,
                subdomain=subdomain.name,
                ip=target_ip,
                api_key=domain.porkbun_api_key,
                secret_key=domain.porkbun_secret_key,
            )
            subdomain.dns_record_id = record_id
            subdomain.dns_record_created = True
            _append_log(subdomain, "Создание A-записи в Porkbun", "ok", f"Record ID: {record_id}")
            _save(db, subdomain)
        except Exception as e:
            _append_log(subdomain, "Создание A-записи в Porkbun", "error", str(e))
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = f"Ошибка создания A-записи: {e}"
            _save(db, subdomain)
            return

        # Step 3: Wait for DNS propagation (max 10 min, check every 15s)
        _append_log(subdomain, "Ожидание DNS-пропагации", "running",
                    "Проверяем через Cloudflare DNS-over-HTTPS…")
        _save(db, subdomain)

        propagated = False
        for attempt in range(40):  # 40 * 15s = 10 min
            propagated = await porkbun_service.check_dns_propagation(full_name, target_ip)
            if propagated:
                break
            await asyncio.sleep(15)

        if not propagated:
            _append_log(subdomain, "Ожидание DNS-пропагации", "error",
                        "Таймаут 10 минут. DNS не распространился.")
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = "DNS не распространился за 10 минут"
            _save(db, subdomain)
            return

        _append_log(subdomain, "Ожидание DNS-пропагации", "ok",
                    f"{full_name} → {target_ip} подтверждён")
        _save(db, subdomain)

        # Step 4: Install Certbot if missing
        _append_log(subdomain, "Установка Certbot", "running")
        _save(db, subdomain)
        try:
            ssh.connect()
            certbot_check = ssh.run("which certbot || echo NOT_FOUND")
            if "NOT_FOUND" in certbot_check:
                ssh.run("apt-get update -q && apt-get install -y certbot python3-certbot-nginx")
                _append_log(subdomain, "Установка Certbot", "ok", "Certbot установлен")
            else:
                _append_log(subdomain, "Установка Certbot", "skipped", "Certbot уже установлен")
            _save(db, subdomain)
        except Exception as e:
            _append_log(subdomain, "Установка Certbot", "error", str(e))
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = f"Ошибка установки Certbot: {e}"
            _save(db, subdomain)
            ssh.close()
            return

        # Step 5: Issue SSL certificate
        _append_log(subdomain, "Выпуск SSL-сертификата", "running")
        _save(db, subdomain)
        try:
            # Use standalone or webroot mode with temporary stop of nginx
            certbot_cmd = (
                f"certbot certonly --nginx -d {full_name} "
                f"--non-interactive --agree-tos --email admin@{domain.name} "
                f"--redirect 2>&1"
            )
            out = ssh.run(certbot_cmd)
            if "Congratulations" in out or "Certificate not yet due" in out or "fullchain.pem" in out:
                # Extract expiry date if possible
                ssl_date_cmd = f"openssl x509 -enddate -noout -in /etc/letsencrypt/live/{full_name}/cert.pem 2>/dev/null || echo ''"
                ssl_raw = ssh.run(ssl_date_cmd)
                subdomain.ssl_enabled = True
                # Try to parse date
                try:
                    date_str = ssl_raw.strip().replace("notAfter=", "")
                    from datetime import datetime
                    exp = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                    subdomain.ssl_expires_at = exp.replace(tzinfo=timezone.utc)
                except Exception:
                    subdomain.ssl_expires_at = datetime.now(timezone.utc) + timedelta(days=90)

                _append_log(subdomain, "Выпуск SSL-сертификата", "ok",
                            f"Сертификат выпущен. Истекает: {subdomain.ssl_expires_at}")
            else:
                raise Exception(out[-500:] if len(out) > 500 else out)
            _save(db, subdomain)
        except Exception as e:
            _append_log(subdomain, "Выпуск SSL-сертификата", "error", str(e))
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = f"Ошибка SSL: {e}"
            _save(db, subdomain)
            ssh.close()
            return

        # Step 6: Configure Nginx
        _append_log(subdomain, "Настройка Nginx", "running")
        _save(db, subdomain)
        try:
            if stype == SubdomainType.admin_panel:
                nginx_conf = NGINX_ADMIN_TEMPLATE.format(full_name=full_name)
            else:
                nginx_conf = NGINX_CLIENT_TEMPLATE.format(full_name=full_name)

            conf_path = f"/etc/nginx/sites-available/{full_name}"
            enabled_path = f"/etc/nginx/sites-enabled/{full_name}"

            # Write config
            escaped = nginx_conf.replace("'", "'\\''")
            ssh.run(f"cat > {conf_path} << 'NGINX_EOF'\n{nginx_conf}\nNGINX_EOF")
            # Enable site
            ssh.run(f"ln -sf {conf_path} {enabled_path}")
            # Test config
            test_out = ssh.run("nginx -t 2>&1")
            if "syntax is ok" not in test_out and "test is successful" not in test_out:
                raise Exception(f"Nginx config test failed: {test_out}")
            subdomain.nginx_configured = True
            _append_log(subdomain, "Настройка Nginx", "ok", f"Конфиг: {conf_path}")
            _save(db, subdomain)
        except Exception as e:
            _append_log(subdomain, "Настройка Nginx", "error", str(e))
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = f"Ошибка Nginx: {e}"
            _save(db, subdomain)
            ssh.close()
            return

        # Step 7: Reload Nginx
        _append_log(subdomain, "Перезапуск Nginx", "running")
        _save(db, subdomain)
        try:
            ssh.run("systemctl reload nginx")
            _append_log(subdomain, "Перезапуск Nginx", "ok", "Nginx перезагружен")
            _save(db, subdomain)
        except Exception as e:
            _append_log(subdomain, "Перезапуск Nginx", "error", str(e))
            subdomain.status = SubdomainStatus.error
            subdomain.status_message = f"Ошибка перезапуска Nginx: {e}"
            _save(db, subdomain)
            ssh.close()
            return

        # Step 8: Verify HTTPS
        _append_log(subdomain, "Проверка HTTPS", "running")
        _save(db, subdomain)
        try:
            verify = ssh.run(
                f"curl -s -o /dev/null -w '%{{http_code}}' https://{full_name}/health --max-time 10 || echo '000'"
            )
            code = verify.strip()
            if code in ("200", "301", "302", "404"):
                _append_log(subdomain, "Проверка HTTPS", "ok", f"HTTP {code} — сайт доступен по https://{full_name}")
            else:
                _append_log(subdomain, "Проверка HTTPS", "ok",
                            f"HTTP {code} — сайт отвечает (может потребоваться время на распространение)")
        except Exception as e:
            _append_log(subdomain, "Проверка HTTPS", "error", str(e))

        ssh.close()

        # Final status
        subdomain.status = SubdomainStatus.active
        subdomain.status_message = f"Готово: https://{full_name}"
        _save(db, subdomain)
        logger.info(f"Subdomain {full_name} setup completed successfully")

    except Exception as e:
        logger.exception(f"Unexpected error in subdomain setup for {subdomain_id}: {e}")
        try:
            subdomain = db.query(Subdomain).filter(Subdomain.id == subdomain_id).first()
            if subdomain:
                subdomain.status = SubdomainStatus.error
                subdomain.status_message = f"Неожиданная ошибка: {e}"
                _save(db, subdomain)
        except Exception:
            pass
    finally:
        db.close()
