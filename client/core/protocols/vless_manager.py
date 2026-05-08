"""
VLESS+Reality manager for Windows — полноценный TUN VPN.

Схема работы:
  1. xray.exe запускается с конфигом (inbound: VLESS Reality, outbound: freedom)
     + встроенный tun inbound (tun mode в xray v25+)
  2. Если xray версия не поддерживает tun — fallback на SOCKS5+tun2socks

xray v25+ поддерживает tun нативно через "tun" inbound.
Требует: xray.exe в папке bin рядом с приложением, wintun.dll там же.
"""

import json
import os
import subprocess
import tempfile
import time
import logging

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000


def _run(args, timeout=10):
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    r = subprocess.run(args, capture_output=True, text=True,
                       timeout=timeout, creationflags=flags)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _popen(args, cwd=None):
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=flags, cwd=cwd
    )


class VlessManager:
    def __init__(self, bin_dir: str):
        self.bin_dir = bin_dir
        self.xray_exe = os.path.join(bin_dir, "xray.exe")
        self.tun2socks_exe = os.path.join(bin_dir, "tun2socks.exe")
        self.xray_proc = None
        self.tun2socks_proc = None
        self.conf_path = None
        self._orig_gw = None       # оригинальный шлюз (для восстановления)
        self._orig_iface = None

    # ── конфигурация xray ────────────────────────────────────────────────────

    def _build_xray_config_tun(self, conn: dict) -> dict:
        """xray v25+ нативный TUN конфиг."""
        return {
            "log": {"loglevel": "warning"},
            "dns": {
                "servers": ["1.1.1.1", "8.8.8.8"],
                "queryStrategy": "UseIPv4"
            },
            "inbounds": [
                {
                    "tag": "tun-in",
                    "type": "tun",
                    "inet4Address": "198.18.0.1/30",
                    "mtu": 1500,
                    "autoRoute": True,
                    "strictRoute": True,
                    "sniff": True,
                    "sniffOverrideDomain": True
                }
            ],
            "outbounds": [
                {
                    "tag": "vless-out",
                    "protocol": "vless",
                    "settings": {
                        "vnext": [{
                            "address": conn["server"]["ip"],
                            "port": conn["port"],
                            "users": [{
                                "id": conn["uuid"],
                                "encryption": "none",
                                "flow": "xtls-rprx-vision"
                            }]
                        }]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "serverName": conn.get("reality_server_name", "www.microsoft.com"),
                            "fingerprint": conn.get("reality_fingerprint", "chrome"),
                            "publicKey": conn["reality_public_key"],
                            "shortId": conn["reality_short_id"],
                        }
                    }
                },
                {"tag": "direct", "protocol": "freedom"},
                {"tag": "block",  "protocol": "blackhole"}
            ],
            "routing": {
                "domainStrategy": "IPIfNonMatch",
                "rules": [
                    # Трафик на сам VPN-сервер — напрямую (иначе петля)
                    {
                        "type": "field",
                        "ip": [conn["server"]["ip"]],
                        "outboundTag": "direct"
                    },
                    # Весь остальной трафик — через VLESS
                    {
                        "type": "field",
                        "network": "tcp,udp",
                        "outboundTag": "vless-out"
                    }
                ]
            }
        }

    def _build_xray_config_socks(self, conn: dict) -> dict:
        """Fallback: xray как SOCKS5 прокси, tun2socks поднимает TUN."""
        return {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "tag": "socks-in",
                    "port": 10808,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": True}
                }
            ],
            "outbounds": [
                {
                    "tag": "vless-out",
                    "protocol": "vless",
                    "settings": {
                        "vnext": [{
                            "address": conn["server"]["ip"],
                            "port": conn["port"],
                            "users": [{
                                "id": conn["uuid"],
                                "encryption": "none",
                                "flow": "xtls-rprx-vision"
                            }]
                        }]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "serverName": conn.get("reality_server_name", "www.microsoft.com"),
                            "fingerprint": conn.get("reality_fingerprint", "chrome"),
                            "publicKey": conn["reality_public_key"],
                            "shortId": conn["reality_short_id"],
                        }
                    }
                },
                {"tag": "direct", "protocol": "freedom"}
            ]
        }

    # ── маршрутизация (для socks+tun2socks режима) ───────────────────────────

    def _get_default_gateway(self) -> tuple[str, str]:
        """Возвращает (gateway_ip, interface_name)."""
        try:
            rc, out, _ = _run(["route", "print", "0.0.0.0"], timeout=5)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    return parts[2], parts[3]
        except Exception:
            pass
        return "", ""

    def _setup_routes(self, server_ip: str, gateway: str):
        """Добавляем маршрут к VPN серверу через реальный шлюз,
           остальное — через TUN (198.18.0.1)."""
        try:
            # Маршрут к VPN серверу через реальный шлюз
            _run(["route", "add", server_ip, "mask", "255.255.255.255", gateway], timeout=5)
            # Весь трафик через TUN
            _run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", "198.18.0.1", "metric", "1"], timeout=5)
        except Exception as e:
            log.warning(f"[VLESS] route setup error: {e}")

    def _teardown_routes(self, server_ip: str, gateway: str):
        try:
            _run(["route", "delete", server_ip], timeout=5)
            _run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "198.18.0.1"], timeout=5)
            # Восстанавливаем дефолтный маршрут
            if gateway:
                _run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", gateway, "metric", "10"], timeout=5)
        except Exception as e:
            log.warning(f"[VLESS] route teardown error: {e}")

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, conn: dict) -> tuple[bool, str]:
        if not os.path.exists(self.xray_exe):
            return False, f"xray.exe не найден в:\n{self.bin_dir}\n\nСкачайте xray-core и положите в папку bin."

        self.disconnect()

        # Пробуем TUN-режим (xray v25+, нужен wintun.dll рядом с xray.exe)
        wintun_ok = os.path.exists(os.path.join(self.bin_dir, "wintun.dll"))
        use_tun_mode = wintun_ok

        if use_tun_mode:
            config = self._build_xray_config_tun(conn)
        else:
            config = self._build_xray_config_socks(conn)

        # Записываем конфиг
        fd, self.conf_path = tempfile.mkstemp(suffix=".json", prefix="xray_vpn_")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)

        # Запускаем xray
        log.info(f"[VLESS] Starting xray, tun_mode={use_tun_mode}")
        try:
            self.xray_proc = _popen(
                [self.xray_exe, "run", "-c", self.conf_path],
                cwd=self.bin_dir  # важно: wintun.dll должна быть в cwd
            )
        except Exception as e:
            return False, f"Не удалось запустить xray.exe: {e}"

        time.sleep(2)
        if self.xray_proc.poll() is not None:
            _, err = self.xray_proc.communicate()
            return False, f"xray.exe завершился с ошибкой:\n{err.decode(errors='replace')[:500]}"

        if use_tun_mode:
            # xray сам поднимает TUN и маршруты через autoRoute
            log.info("[VLESS] TUN mode active via xray")
            server_name = conn.get("client_name", "")
            conn_type = "cascade (RU→EU)" if conn.get("connection_type") == "cascade" else "direct"
            return True, (
                f"VLESS Reality подключён\n{server_name}\n"
                f"Тип: {conn_type}\n\n"
                f"Весь трафик идёт через VPN (TUN режим)."
            )
        else:
            # Fallback: SOCKS5 + tun2socks
            return self._start_tun2socks(conn)

    def _start_tun2socks(self, conn: dict) -> tuple[bool, str]:
        """Запускает tun2socks поверх xray SOCKS5."""
        if not os.path.exists(self.tun2socks_exe):
            return False, (
                "tun2socks.exe не найден и wintun.dll отсутствует.\n"
                "Положите wintun.dll в папку bin рядом с xray.exe."
            )

        server_ip = conn["server"]["ip"]
        gw, iface = self._get_default_gateway()
        self._orig_gw = gw

        log.info(f"[VLESS] Starting tun2socks, gw={gw}")
        try:
            self.tun2socks_proc = _popen([
                self.tun2socks_exe,
                "-device", "tun://tun0",
                "-proxy", "socks5://127.0.0.1:10808",
                "-interface", iface or "",
                "-loglevel", "warning"
            ], cwd=self.bin_dir)
        except Exception as e:
            return False, f"Не удалось запустить tun2socks.exe: {e}"

        time.sleep(2)
        if self.tun2socks_proc.poll() is not None:
            _, err = self.tun2socks_proc.communicate()
            return False, f"tun2socks завершился:\n{err.decode(errors='replace')[:300]}"

        # Настраиваем маршруты
        self._setup_routes(server_ip, gw)

        server_name = conn.get("client_name", "")
        conn_type = "cascade (RU→EU)" if conn.get("connection_type") == "cascade" else "direct"
        return True, (
            f"VLESS Reality подключён\n{server_name}\n"
            f"Тип: {conn_type}\n\n"
            f"Весь трафик идёт через VPN."
        )

    def disconnect(self):
        # Убиваем tun2socks
        if self.tun2socks_proc:
            try:
                self.tun2socks_proc.terminate()
                self.tun2socks_proc.wait(timeout=3)
            except Exception:
                try:
                    self.tun2socks_proc.kill()
                except Exception:
                    pass
            self.tun2socks_proc = None

        # Убиваем xray
        if self.xray_proc:
            try:
                self.xray_proc.terminate()
                self.xray_proc.wait(timeout=3)
            except Exception:
                try:
                    self.xray_proc.kill()
                except Exception:
                    pass
            self.xray_proc = None

        # Удаляем конфиг
        if self.conf_path and os.path.exists(self.conf_path):
            try:
                os.unlink(self.conf_path)
            except Exception:
                pass
            self.conf_path = None

        # Восстанавливаем маршруты если были изменены
        if self._orig_gw:
            try:
                _run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "198.18.0.1"], timeout=5)
                _run(["route", "add", "0.0.0.0", "mask", "0.0.0.0",
                      self._orig_gw, "metric", "10"], timeout=5)
            except Exception:
                pass
            self._orig_gw = None

    def is_running(self) -> bool:
        if self.xray_proc and self.xray_proc.poll() is None:
            return True
        return False
