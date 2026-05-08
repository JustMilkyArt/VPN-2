"""
API client — авторизация + получение подключений с VPN Admin бэкенда.
"""

import requests
import pyotp
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Отключаем предупреждения про SSL (бэкенд без HTTPS)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ApiClient:
    def __init__(self, base_url: str, username: str, password: str, totp_secret: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = False

    def login(self) -> bool:
        try:
            # Шаг 1: логин
            r = self.session.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=10,
            )
            data = r.json()
            if data.get("phase") != "totp":
                log.error(f"Unexpected login response: {data}")
                return False

            temp_token = data["temp_token"]

            # Шаг 2: TOTP (генерируем текущий код из секрета)
            totp_code = pyotp.TOTP(self.totp_secret).now()
            r2 = self.session.post(
                f"{self.base_url}/api/v1/auth/totp-verify",
                json={"temp_token": temp_token, "totp_code": totp_code},
                timeout=10,
            )
            data2 = r2.json()
            if "access_token" not in data2:
                log.error(f"No access token in response: {data2}")
                return False

            self.token = data2["access_token"]
            log.info("API login successful")
            return True

        except Exception as e:
            log.error(f"Login error: {e}")
            return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _ensure_token(self) -> bool:
        if not self.token:
            return self.login()
        return True

    def get_connections(self) -> list[dict]:
        """Возвращает плоский список всех подключений."""
        if not self._ensure_token():
            return []
        try:
            r = self.session.get(
                f"{self.base_url}/api/v1/connections/grouped",
                headers=self._headers(),
                timeout=15,
            )
            if r.status_code == 401:
                self.token = None
                if not self.login():
                    return []
                r = self.session.get(
                    f"{self.base_url}/api/v1/connections/grouped",
                    headers=self._headers(),
                    timeout=15,
                )

            groups = r.json()
            connections = []
            for group in groups:
                for conn in group.get("direct", []):
                    connections.append(conn)
                for conn in group.get("cascade", []):
                    connections.append(conn)
            log.info(f"Loaded {len(connections)} connections")
            return connections

        except Exception as e:
            log.error(f"get_connections error: {e}")
            return []
