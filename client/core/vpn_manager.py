"""
VPN Manager — оркестрирует все три протокола.
"""

import os
import sys
import logging
from typing import Optional

log = logging.getLogger(__name__)


def get_bin_dir() -> str:
    # 1. PyInstaller .exe — бинарники распакованы во временную папку
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "bin")
    # 2. Переменная окружения (Setup-скрипт явно передаёт путь)
    env_bin = os.environ.get("VPNCLIENT_BIN_DIR")
    if env_bin and os.path.isdir(env_bin):
        return env_bin
    # 3. bin\ рядом с main.py (прямой запуск из исходников)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_bin = os.path.join(here, "bin")
    if os.path.isdir(local_bin):
        return local_bin
    # 4. Стандартный путь установки через Setup-скрипт
    appdata_bin = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "VPNClient", "bin"
    )
    return appdata_bin


class VpnManager:
    def __init__(self):
        from .protocols.vless_manager import VlessManager
        from .protocols.awg_manager import AwgManager
        from .protocols.naive_manager import NaiveManager

        bin_dir = get_bin_dir()
        self.vless  = VlessManager(bin_dir)
        self.awg    = AwgManager()
        self.naive  = NaiveManager(bin_dir)

        self.active_conn: Optional[dict] = None
        self.active_proto: Optional[str] = None

    # ── connect ───────────────────────────────────────────────────────────────

    def connect(self, conn: dict) -> tuple[bool, str]:
        self.disconnect()

        proto = conn.get("protocol", "")
        log.info(f"Connecting: {conn.get('client_name')} [{proto}]")

        if proto == "vless_reality":
            ok, msg = self.vless.connect(conn)
        elif proto == "amnezia_wg":
            ok, msg = self.awg.connect(conn)
        elif proto == "naive_proxy":
            ok, msg = self.naive.connect(conn)
        else:
            return False, f"Неизвестный протокол: {proto}"

        if ok:
            self.active_conn  = conn
            self.active_proto = proto

        return ok, msg

    # ── disconnect ────────────────────────────────────────────────────────────

    def disconnect(self):
        if not self.active_proto:
            return
        log.info(f"Disconnecting [{self.active_proto}]")
        if self.active_proto == "vless_reality":
            self.vless.disconnect()
        elif self.active_proto == "amnezia_wg":
            self.awg.disconnect()
        elif self.active_proto == "naive_proxy":
            self.naive.disconnect()
        self.active_conn  = None
        self.active_proto = None

    # ── status ────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        if self.active_proto == "vless_reality":
            return self.vless.is_running()
        elif self.active_proto == "amnezia_wg":
            return self.awg.is_running()
        elif self.active_proto == "naive_proxy":
            return self.naive.is_running()
        return False

    def active_name(self) -> Optional[str]:
        return self.active_conn.get("client_name") if self.active_conn else None
