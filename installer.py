"""
VPN Client Installer / Launcher
================================
Запускать от имени администратора (Run as Administrator).

Шаги:
  1. Скачивает xray.exe, wintun.dll, tun2socks.exe, naive.exe → папка bin\
  2. Скачивает и тихо устанавливает AmneziaWG MSI
  3. Устанавливает Python-зависимости (PyQt6, requests, pyotp)
  4. Запускает основное приложение VPN клиента

Всё происходит в одном окне с прогресс-баром.
"""

import os
import sys
import subprocess
import tempfile
import threading
import zipfile
import urllib.request
import urllib.error
import time

# ─── Пути ────────────────────────────────────────────────────────────────────

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BIN_DIR   = os.path.join(BASE_DIR, "bin")
MAIN_PY   = os.path.join(BASE_DIR, "main.py")

# ─── Файлы для скачивания ─────────────────────────────────────────────────────

DOWNLOADS = [
    {
        "name":    "xray.exe",
        "url":     "https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip",
        "dest":    os.path.join(BIN_DIR, "xray.exe"),
        "zip_member": "xray.exe",
        "label":   "Xray-core (VLESS Reality)",
    },
    {
        "name":    "wintun.dll",
        "url":     "https://www.wintun.net/builds/wintun-0.14.1.zip",
        "dest":    os.path.join(BIN_DIR, "wintun.dll"),
        "zip_member": "wintun/bin/amd64/wintun.dll",
        "label":   "WinTUN driver",
    },
    {
        "name":    "tun2socks.exe",
        "url":     "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip",
        "dest":    os.path.join(BIN_DIR, "tun2socks.exe"),
        "zip_member": "tun2socks-windows-amd64.exe",
        "label":   "tun2socks",
    },
    {
        "name":    "naive.exe",
        "url":     "https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip",
        "dest":    os.path.join(BIN_DIR, "naive.exe"),
        "zip_member": "naiveproxy-v148.0.7778.96-2-win-x64/naive.exe",
        "label":   "NaiveProxy",
    },
]

AWG_MSI_URL  = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"
AWG_MSI_NAME = "amneziawg-amd64-2.0.0.msi"

PYTHON_DEPS = ["PyQt6", "requests", "pyotp"]

# ─── Проверка запуска с правами администратора ────────────────────────────────

def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Перезапустить скрипт с правами администратора через UAC."""
    import ctypes
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    sys.exit(0)

# ─── Вспомогательные функции ──────────────────────────────────────────────────

def download_file(url: str, dest: str, progress_cb=None) -> None:
    """Скачать файл с прогрессом."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "VPNClient/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done  = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(done / total)


def extract_from_zip(zip_path: str, member: str, dest: str) -> None:
    """Извлечь один файл из ZIP."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # Ищем точное совпадение или суффикс (на случай вложенных папок)
        match = None
        for n in names:
            if n == member or n.endswith("/" + member.split("/")[-1]):
                match = n
                break
        if not match:
            raise FileNotFoundError(
                f"Файл '{member}' не найден в архиве. Доступные: {names[:10]}"
            )
        data = zf.read(match)
    with open(dest, "wb") as f:
        f.write(data)


def is_awg_installed() -> bool:
    awg_paths = [
        r"C:\Program Files\AmneziaWG\wireguard.exe",
        r"C:\Program Files (x86)\AmneziaWG\wireguard.exe",
    ]
    return any(os.path.exists(p) for p in awg_paths)


def install_awg(msi_path: str) -> None:
    """Тихая установка AmneziaWG MSI."""
    subprocess.run(
        ["msiexec", "/i", msi_path, "/quiet", "/norestart"],
        check=True, timeout=120
    )


def install_python_deps(deps: list, log_cb=None) -> None:
    """Установить Python зависимости через pip."""
    for dep in deps:
        if log_cb:
            log_cb(f"pip install {dep}…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", dep, "--quiet"],
            check=True, timeout=120
        )

# ─── Installer с GUI (tkinter — встроен в Python) ─────────────────────────────

def run_installer_gui():
    """Запустить установщик с GUI на tkinter."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("VPN Client — Установка")
    root.resizable(False, False)
    root.geometry("520x420")
    root.configure(bg="#10131E")

    # Стили
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure(
        "TProgressbar",
        background="#6C63FF",
        troughcolor="#181D2B",
        bordercolor="#252B3B",
        lightcolor="#6C63FF",
        darkcolor="#6C63FF",
    )

    # ── Заголовок ──────────────────────────────────────────────────────────
    frm_top = tk.Frame(root, bg="#10131E")
    frm_top.pack(fill="x", padx=24, pady=(24, 8))

    tk.Label(
        frm_top, text="🔒  VPN Client",
        font=("Segoe UI", 18, "bold"),
        fg="#FFFFFF", bg="#10131E"
    ).pack(anchor="w")

    tk.Label(
        frm_top, text="Установка компонентов…",
        font=("Segoe UI", 9),
        fg="#555555", bg="#10131E"
    ).pack(anchor="w")

    # ── Прогресс ───────────────────────────────────────────────────────────
    frm_pb = tk.Frame(root, bg="#10131E")
    frm_pb.pack(fill="x", padx=24, pady=8)

    lbl_step = tk.Label(
        frm_pb, text="Подготовка…",
        font=("Segoe UI", 10),
        fg="#AAAAAA", bg="#10131E", anchor="w"
    )
    lbl_step.pack(fill="x")

    pb = ttk.Progressbar(frm_pb, length=472, mode="determinate")
    pb.pack(fill="x", pady=6)

    lbl_pct = tk.Label(
        frm_pb, text="0%",
        font=("Segoe UI", 8),
        fg="#555555", bg="#10131E", anchor="e"
    )
    lbl_pct.pack(fill="x")

    # ── Лог ────────────────────────────────────────────────────────────────
    frm_log = tk.Frame(root, bg="#10131E")
    frm_log.pack(fill="both", expand=True, padx=24, pady=(0, 12))

    log_box = tk.Text(
        frm_log,
        font=("Consolas", 8),
        bg="#0A0C14", fg="#446644",
        relief="flat", bd=0,
        state="disabled", wrap="word",
        height=10,
    )
    sb = tk.Scrollbar(frm_log, command=log_box.yview, bg="#181D2B")
    log_box.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    log_box.pack(fill="both", expand=True)

    # ── Кнопка ─────────────────────────────────────────────────────────────
    btn = tk.Button(
        root,
        text="Запустить VPN Client",
        font=("Segoe UI", 11, "bold"),
        bg="#6C63FF", fg="#FFFFFF",
        activebackground="#7D75FF", activeforeground="#FFFFFF",
        relief="flat", bd=0,
        padx=20, pady=10,
        state="disabled",
        cursor="hand2",
    )
    btn.pack(padx=24, pady=(0, 20), fill="x")

    # ── Вспомогательные функции для обновления UI ──────────────────────────

    def log(msg: str):
        def _do():
            log_box.configure(state="normal")
            log_box.insert("end", msg + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        root.after(0, _do)

    def set_step(text: str):
        root.after(0, lambda: lbl_step.configure(text=text))

    def set_progress(value: float):
        """value: 0.0 … 1.0 (общий прогресс)"""
        pct = int(value * 100)
        root.after(0, lambda: pb.configure(value=pct))
        root.after(0, lambda: lbl_pct.configure(text=f"{pct}%"))

    def enable_launch():
        root.after(0, lambda: btn.configure(state="normal"))

    def on_launch():
        btn.configure(state="disabled")
        root.after(200, lambda: launch_main_app(root))

    btn.configure(command=on_launch)

    # ── Основной поток установки ───────────────────────────────────────────

    def install_thread():
        total_steps = len(DOWNLOADS) + 2  # +AWG +deps
        current = 0

        os.makedirs(BIN_DIR, exist_ok=True)

        # 1. Скачиваем бинарники
        for item in DOWNLOADS:
            dest    = item["dest"]
            label   = item["label"]
            set_step(f"Скачивание: {label}")

            if os.path.exists(dest):
                log(f"✓ {item['name']} уже есть, пропуск")
                current += 1
                set_progress(current / total_steps)
                continue

            log(f"⬇ {label} …")
            tmp_zip = dest + ".tmp"
            try:
                def _prog(frac, _lbl=label):
                    partial = (current + frac) / total_steps
                    set_progress(partial)

                download_file(item["url"], tmp_zip, progress_cb=_prog)

                if item["url"].endswith(".zip"):
                    log(f"  Распаковка {item['name']}…")
                    extract_from_zip(tmp_zip, item["zip_member"], dest)
                    os.unlink(tmp_zip)
                else:
                    os.rename(tmp_zip, dest)

                log(f"✓ {item['name']} готов")

            except Exception as e:
                log(f"✗ Ошибка: {e}")
                if os.path.exists(tmp_zip):
                    try: os.unlink(tmp_zip)
                    except: pass

            current += 1
            set_progress(current / total_steps)

        # 2. AmneziaWG
        set_step("AmneziaWG — проверка установки…")
        if is_awg_installed():
            log("✓ AmneziaWG уже установлен")
        else:
            log(f"⬇ AmneziaWG MSI …")
            msi_path = os.path.join(tempfile.gettempdir(), AWG_MSI_NAME)
            try:
                download_file(AWG_MSI_URL, msi_path)
                log("  Установка AmneziaWG (тихая)…")
                install_awg(msi_path)
                log("✓ AmneziaWG установлен")
            except Exception as e:
                log(f"✗ Ошибка установки AmneziaWG: {e}")
                log("  → Установите вручную: https://github.com/amnezia-vpn/amneziawg-windows-client/releases")
        current += 1
        set_progress(current / total_steps)

        # 3. Python зависимости
        set_step("Установка Python зависимостей…")
        try:
            install_python_deps(PYTHON_DEPS, log_cb=log)
            log("✓ Зависимости установлены")
        except Exception as e:
            log(f"✗ pip error: {e}")
        current += 1
        set_progress(1.0)

        set_step("✅ Установка завершена! Нажмите кнопку для запуска.")
        log("\n🚀 Всё готово — нажмите «Запустить VPN Client»")
        enable_launch()

    threading.Thread(target=install_thread, daemon=True).start()
    root.mainloop()


def launch_main_app(parent_window=None):
    """Запустить основное приложение VPN клиента."""
    if parent_window:
        parent_window.destroy()

    if not os.path.exists(MAIN_PY):
        # Пробуем найти main.py рядом с installer
        alt = os.path.join(BASE_DIR, "main.py")
        if not os.path.exists(alt):
            import tkinter.messagebox as mb
            mb.showerror("Ошибка", f"main.py не найден:\n{MAIN_PY}")
            return

    # Запускаем main.py
    subprocess.Popen(
        [sys.executable, MAIN_PY],
        cwd=BASE_DIR,
        creationflags=0x00000010  # CREATE_NEW_CONSOLE — своё окно
    )


# ─── Точка входа ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # На Windows требуем права администратора
    if sys.platform == "win32" and not is_admin():
        relaunch_as_admin()
        sys.exit(0)

    run_installer_gui()
