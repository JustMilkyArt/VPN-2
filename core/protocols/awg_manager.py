"""
AmneziaWG manager for Windows.

Стратегия:
- Использует wireguard.exe из установленного AmneziaWG клиента
  (C:\Program Files\AmneziaWG\wireguard.exe)
- /installtunnelservice — поднимает TUN туннель (полноценный VPN)
- /uninstalltunnelservice — отключает
- Требует: AmneziaWG установлен на Windows (amneziawg-amd64.msi)
"""

import os
import re
import subprocess
import tempfile
import time
import logging

log = logging.getLogger(__name__)

# Стандартные пути установки AmneziaWG на Windows
AWG_SEARCH_PATHS = [
    r"C:\Program Files\AmneziaWG\wireguard.exe",
    r"C:\Program Files (x86)\AmneziaWG\wireguard.exe",
    r"C:\Program Files\WireGuard\wireguard.exe",   # fallback — стандартный WG (без junk)
]


def _find_awg_exe() -> str | None:
    for p in AWG_SEARCH_PATHS:
        if os.path.exists(p):
            return p
    return None


def _run(args: list, timeout: int = 15) -> tuple[int, str, str]:
    """Run a command hidden (no console window)."""
    CREATE_NO_WINDOW = 0x08000000
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    r = subprocess.run(
        args, capture_output=True, text=True,
        timeout=timeout, creationflags=flags
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


class AwgManager:
    def __init__(self):
        self.wireguard_exe: str | None = None
        self.tunnel_name: str | None = None
        self.conf_path: str | None = None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_exe(self) -> str | None:
        if self.wireguard_exe and os.path.exists(self.wireguard_exe):
            return self.wireguard_exe
        self.wireguard_exe = _find_awg_exe()
        return self.wireguard_exe

    @staticmethod
    def _safe_name(conn: dict) -> str:
        raw = conn.get("client_name", f"vpn_{conn['id']}")
        # Убираем эмодзи и спецсимволы, оставляем ASCII + цифры + _-
        ascii_only = raw.encode("ascii", "ignore").decode()
        cleaned = re.sub(r"[^\w\s\-]", "", ascii_only)
        cleaned = re.sub(r"\s+", "_", cleaned.strip())
        return (cleaned or f"vpn_{conn['id']}")[:32]

    @staticmethod
    def _build_conf(conn: dict) -> str:
        """Возвращает содержимое .conf файла."""
        if conn.get("config_text"):
            return conn["config_text"]
        lines = [
            "[Interface]",
            f"PrivateKey = {conn['wg_client_private_key']}",
            f"Address = {conn['wg_client_ip']}/32",
            "DNS = 1.1.1.1, 8.8.8.8",
            f"Jc = {conn.get('awg_junk_packet_count', 4)}",
            f"Jmin = {conn.get('awg_junk_packet_min_size', 40)}",
            f"Jmax = {conn.get('awg_junk_packet_max_size', 70)}",
            f"S1 = {conn.get('awg_s1', 50)}",
            f"S2 = {conn.get('awg_s2', 100)}",
            f"H1 = {conn.get('awg_h1', 1)}",
            f"H2 = {conn.get('awg_h2', 2)}",
            f"H3 = {conn.get('awg_h3', 3)}",
            f"H4 = {conn.get('awg_h4', 4)}",
            "",
            "[Peer]",
            f"PublicKey = {conn['wg_public_key']}",
            f"PresharedKey = {conn['wg_preshared_key']}",
            f"Endpoint = {conn['server']['ip']}:{conn['port']}",
            "AllowedIPs = 0.0.0.0/0, ::/0",
            "PersistentKeepalive = 25",
        ]
        return "\n".join(lines)

    # ── public API ────────────────────────────────────────────────────────────

    def is_installed(self) -> bool:
        return self._get_exe() is not None

    def connect(self, conn: dict) -> tuple[bool, str]:
        exe = self._get_exe()
        if not exe:
            return False, (
                "AmneziaWG не установлен.\n\n"
                "Скачайте и установите:\n"
                "https://github.com/amnezia-vpn/amneziawg-windows-client/releases\n"
                "(файл amneziawg-amd64-X.X.X.msi)"
            )

        self.disconnect()

        conf_text = self._build_conf(conn)
        tunnel_name = self._safe_name(conn)

        # Сохраняем конфиг в постоянном месте (wireguard.exe читает файл)
        conf_dir = os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"), "VPNClient", "tunnels")
        os.makedirs(conf_dir, exist_ok=True)
        conf_path = os.path.join(conf_dir, f"{tunnel_name}.conf")

        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(conf_text)

        self.conf_path = conf_path
        self.tunnel_name = tunnel_name

        log.info(f"[AWG] Installing tunnel service: {tunnel_name}")
        try:
            rc, out, err = _run([exe, "/installtunnelservice", conf_path], timeout=20)
        except subprocess.TimeoutExpired:
            return False, "Таймаут при установке AWG туннеля"
        except Exception as e:
            return False, f"Ошибка запуска wireguard.exe: {e}"

        if rc != 0:
            return False, f"wireguard.exe вернул ошибку ({rc}):\n{err or out}"

        # Ждём поднятия интерфейса
        time.sleep(2)
        if not self.is_running():
            # Иногда сервис стартует дольше
            time.sleep(3)

        log.info(f"[AWG] Tunnel up: {tunnel_name}")
        server_name = conn.get("client_name", "")
        conn_type = "cascade (RU→EU)" if conn.get("connection_type") == "cascade" else "direct"
        return True, f"AmneziaWG подключён\n{server_name}\nТип: {conn_type}\n\nВесь трафик идёт через VPN."

    def disconnect(self):
        if self.tunnel_name:
            exe = self._get_exe()
            if exe:
                try:
                    log.info(f"[AWG] Uninstalling tunnel: {self.tunnel_name}")
                    _run([exe, "/uninstalltunnelservice", self.tunnel_name], timeout=10)
                except Exception as e:
                    log.warning(f"[AWG] Disconnect error: {e}")
            self.tunnel_name = None

        if self.conf_path:
            try:
                if os.path.exists(self.conf_path):
                    os.unlink(self.conf_path)
            except Exception:
                pass
            self.conf_path = None

    def is_running(self) -> bool:
        if not self.tunnel_name:
            return False
        try:
            rc, out, _ = _run(
                ["sc", "query", f"WireGuardTunnel${self.tunnel_name}"],
                timeout=5
            )
            return "RUNNING" in out
        except Exception:
            return False
