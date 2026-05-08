"""
VPN Client — точка входа.
"""

import sys
import os
import logging

# Логирование в файл рядом с .exe
log_path = os.path.join(os.path.expanduser("~"), "vpnclient.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from config import API_BASE_URL, API_USERNAME, API_PASSWORD, API_TOTP_SECRET, APP_NAME
from core.api_client import ApiClient
from core.vpn_manager import VpnManager
from ui.main_window import MainWindow


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    api = ApiClient(API_BASE_URL, API_USERNAME, API_PASSWORD, API_TOTP_SECRET)
    vpn = VpnManager()

    window = MainWindow(vpn, api)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
