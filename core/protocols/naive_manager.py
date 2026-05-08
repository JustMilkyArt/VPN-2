"""
NaiveProxy manager for Windows — полноценный TUN VPN.

Схема:
  1. naive.exe → SOCKS5 на 127.0.0.1:10808
  2. tun2socks.exe → TUN адаптер поверх SOCKS5
  3. Маршруты: весь трафик → TUN, VPN сервер → реальный шлюз
"""

import os
import subprocess
import json
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


class NaiveManager:
    def __init__(self, bin_dir: str):
        self.bin_dir = bin_dir
        self.naive_exe = os.path.join(bin_dir, "naive.exe")
        self.tun2socks_exe = os.path.join(bin_dir, "tun2socks.exe")
        self.naive_proc = None
        self.tun2socks_proc = None
        self.conf_path = None
        self._orig_gw = None
        self._server_ip = None

    def _get_default_gateway(self) -> tuple[str, str]:
        try:
            rc, out, _ = _run(["route", "print", "0.0.0.0"], timeout=5)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    return parts[2], parts[3]
        except Exception:
            pass
        return "", ""

    def _build_naive_config(self, conn: dict) -> dict:
        host = conn.get("np_domain") or conn["server"]["ip"]
        port = conn["port"]
        user = conn.get("np_user", "vpnuser")
        password = conn["password"]
        return {
            "listen": "socks://127.0.0.1:10808",
            "proxy": f"https://{user}:{password}@{host}:{port}",
            "log": ""
        }

    def _setup_routes(self, server_ip: str, gw: str):
        try:
            _run(["route", "add", server_ip, "mask", "255.255.255.255", gw], timeout=5)
            _run(["route", "add", "0.0.0.0", "mask", "0.0.0.0", "198.18.0.1", "metric", "1"], timeout=5)
        except Exception as e:
            log.warning(f"[NaiveProxy] route error: {e}")

    def _teardown_routes(self):
        try:
            if self._server_ip:
                _run(["route", "delete", self._server_ip], timeout=5)
            _run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", "198.18.0.1"], timeout=5)
            if self._orig_gw:
                _run(["route", "add", "0.0.0.0", "mask", "0.0.0.0",
                      self._orig_gw, "metric", "10"], timeout=5)
        except Exception as e:
            log.warning(f"[NaiveProxy] route teardown error: {e}")

    def connect(self, conn: dict) -> tuple[bool, str]:
        if not os.path.exists(self.naive_exe):
            return False, (
                f"naive.exe не найден в:\n{self.bin_dir}\n\n"
                "Скачайте naiveproxy и положите naive.exe в папку bin."
            )
        if not os.path.exists(self.tun2socks_exe):
            return False, (
                f"tun2socks.exe не найден в:\n{self.bin_dir}\n\n"
                "Скачайте tun2socks и положите в папку bin."
            )

        self.disconnect()

        # Запись конфига
        config = self._build_naive_config(conn)
        fd, self.conf_path = tempfile.mkstemp(suffix=".json", prefix="naive_vpn_")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)

        # Запуск naive
        log.info(f"[NaiveProxy] Starting naive → {config['proxy']}")
        try:
            self.naive_proc = _popen(
                [self.naive_exe, f"--config={self.conf_path}"],
                cwd=self.bin_dir
            )
        except Exception as e:
            return False, f"Не удалось запустить naive.exe: {e}"

        time.sleep(1.5)
        if self.naive_proc.poll() is not None:
            _, err = self.naive_proc.communicate()
            return False, f"naive.exe завершился:\n{err.decode(errors='replace')[:400]}"

        # Получаем шлюз
        gw, iface = self._get_default_gateway()
        self._orig_gw = gw

        host = conn.get("np_domain") or conn["server"]["ip"]
        # Для маршрута нужен IP, а не домен
        server_ip = conn["server"]["ip"]
        self._server_ip = server_ip

        # Запуск tun2socks
        log.info(f"[NaiveProxy] Starting tun2socks, gw={gw}")
        try:
            self.tun2socks_proc = _popen([
                self.tun2socks_exe,
                "-device", "tun://tun0",
                "-proxy", "socks5://127.0.0.1:10808",
                "-loglevel", "warning"
            ], cwd=self.bin_dir)
        except Exception as e:
            self.naive_proc.terminate()
            self.naive_proc = None
            return False, f"Не удалось запустить tun2socks.exe: {e}"

        time.sleep(2)
        if self.tun2socks_proc.poll() is not None:
            _, err = self.tun2socks_proc.communicate()
            self.naive_proc.terminate()
            self.naive_proc = None
            return False, f"tun2socks завершился:\n{err.decode(errors='replace')[:300]}"

        # Маршруты
        self._setup_routes(server_ip, gw)

        server_name = conn.get("client_name", "")
        conn_type = "cascade (RU→EU)" if conn.get("connection_type") == "cascade" else "direct"
        return True, (
            f"NaiveProxy подключён\n{server_name}\n"
            f"Тип: {conn_type}\n\n"
            f"Весь трафик идёт через VPN."
        )

    def disconnect(self):
        for proc_attr in ("tun2socks_proc", "naive_proc"):
            proc = getattr(self, proc_attr)
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                setattr(self, proc_attr, None)

        if self.conf_path and os.path.exists(self.conf_path):
            try:
                os.unlink(self.conf_path)
            except Exception:
                pass
            self.conf_path = None

        self._teardown_routes()
        self._orig_gw = None
        self._server_ip = None

    def is_running(self) -> bool:
        return (self.naive_proc is not None and
                self.naive_proc.poll() is None)
