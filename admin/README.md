# 🛡️ VPN Infrastructure Manager — MVP

Централизованная система управления VPN-инфраструктурой с автоматическим деплоем через SSH.

## 🏗️ Архитектура

```
Flutter Web Admin
      ↓ HTTP API
FastAPI Backend (Python)
      ↓ SSH (paramiko)
SQLite DB  ←→  VPN Servers
                  ↓
           Xray-core + Reality
           NaiveProxy (Caddy)
           Trojan
           WARP (fallback)
```

### Сетевой поток
```
Client → RU Server (entry) → EU Server (exit) → Internet
                    ↓ fallback
                  WARP → Internet
```

## 📁 Структура проекта

```
vpn-admin/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/v1/      # REST endpoints
│   │   ├── core/        # Config, Security (JWT/bcrypt)
│   │   ├── db/          # SQLAlchemy + SQLite
│   │   ├── models/      # ORM модели
│   │   ├── schemas/     # Pydantic схемы
│   │   └── services/    # SSH, Deploy, Config генераторы
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── web_admin/       # HTML/CSS/JS Admin Panel
│       ├── index.html
│       ├── css/app.css
│       └── js/
│           ├── api.js       # API клиент
│           ├── ui.js        # UI утилиты
│           ├── servers.js   # Вкладка Серверы
│           ├── connections.js # Вкладка Подключения
│           └── app.js       # Инициализация
├── infra/
│   ├── scripts/         # Bash-скрипты деплоя
│   │   ├── install_xray.sh
│   │   ├── setup_reality.sh
│   │   ├── install_naiveproxy.sh
│   │   ├── install_trojan.sh
│   │   ├── setup_warp.sh
│   │   ├── restart_services.sh
│   │   └── deploy_backend.sh  # Деплой всей системы
│   ├── nginx.conf
│   └── vpn-admin-backend.service
└── docs/
```

## 🚀 Быстрый деплой на сервер

### 1. На новом Ubuntu 24.04 сервере

```bash
# Скачать и запустить скрипт деплоя
curl -sSL https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main/infra/scripts/deploy_backend.sh | sudo bash
```

### 2. Или вручную

```bash
# Клонировать репо
git clone https://github.com/JustMilkyArt/VPN-2.git /opt/vpn-admin
cd /opt/vpn-admin/backend

# Настроить окружение
cp .env.example .env
nano .env  # Изменить SECRET_KEY, ADMIN_PASSWORD

# Python venv
python3 -m venv /opt/vpn-admin/venv
/opt/vpn-admin/venv/bin/pip install -r requirements.txt

# Создать пользователя
useradd -r -s /bin/bash -d /opt/vpn-admin vpnadmin
chown -R vpnadmin:vpnadmin /opt/vpn-admin

# systemd
cp /opt/vpn-admin/infra/vpn-admin-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vpn-admin-backend

# Nginx
apt install -y nginx
cp /opt/vpn-admin/infra/nginx.conf /etc/nginx/sites-available/vpn-admin
ln -sf /etc/nginx/sites-available/vpn-admin /etc/nginx/sites-enabled/vpn-admin
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 3. Доступ
- **Web Admin:** http://SERVER_IP
- **API Docs:** http://SERVER_IP/docs
- **Логин по умолчанию:** admin / changeme123 (сменить в .env!)

## 🔧 Стек технологий

| Компонент | Технология |
|-----------|------------|
| Backend | FastAPI + Python 3.11+ |
| База данных | SQLite (SQLAlchemy ORM) |
| Аутентификация | JWT + bcrypt |
| SSH | Paramiko |
| Frontend | Vanilla JS + Tailwind CSS |
| VPN движок | Xray-core (VLESS, Trojan) |
| Скрытие трафика | Reality protocol |
| Fallback | Cloudflare WARP |
| Web-сервер | Nginx + Uvicorn |

## 📡 API Endpoints

### Auth
- `POST /api/v1/auth/login` — получить JWT токен
- `GET /api/v1/auth/me` — текущий пользователь

### Servers
- `GET /api/v1/servers/` — список серверов
- `POST /api/v1/servers/` — добавить сервер
- `POST /api/v1/servers/{id}/ping` — проверить SSH
- `POST /api/v1/servers/{id}/install` — установить VPN стек
- `POST /api/v1/servers/{id}/restart` — перезапустить сервисы
- `POST /api/v1/servers/check-all-status` — проверить все

### Connections
- `GET /api/v1/connections/grouped` — подключения по серверам
- `POST /api/v1/connections/` — создать + автодеплой
- `GET /api/v1/connections/{id}/client-config` — конфиг клиента
- `POST /api/v1/connections/{id}/toggle` — вкл/выкл
- `DELETE /api/v1/connections/{id}` — удалить

## 🔐 Поддерживаемые протоколы

| Протокол | Защита | Статус |
|----------|--------|--------|
| VLESS + Reality | Максимальная (мимикрия TLS) | ✅ MVP |
| Trojan | TLS-туннель | ✅ MVP |
| NaiveProxy | HTTPS-прокси | ✅ MVP |
| WARP | Cloudflare tunnel | ✅ MVP |

## 🗄️ База данных

### Таблица `servers`
- id, name, ip, country, role (RU/EU/MIXED)
- ssh_user, ssh_port, ssh_key, ssh_password
- status, is_active
- xray_installed, naiveproxy_installed, trojan_installed, warp_installed
- domain, notes

### Таблица `connections`
- id, name, server_id, protocol, port
- uuid (VLESS), password (Trojan/NaiveProxy)
- reality_public_key, reality_private_key, reality_short_id
- client_link, config_json
- status, is_active, exit_server_id

### Таблица `admin_users`
- id, username, password_hash, is_active

## 📋 Следующие шаги (Roadmap)

- [ ] Flutter Mobile app
- [ ] Ping/latency мониторинг
- [ ] Автоматический failover (WARP при недоступности EU)
- [ ] Мультидоменная поддержка
- [ ] Статистика трафика
- [ ] Автопродление SSL (Let's Encrypt)
- [ ] Webhook уведомления (Telegram bot)
- [ ] Пользовательский портал (регистрация, тарифы)

## 📌 Лицензия

MIT
