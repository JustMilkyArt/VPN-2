"""
VPN Client Installer — GUI на tkinter (встроен в Python, без PyQt6)
Запускается через pythonw.exe — без консоли.
UAC запрашивается самим .bat файлом ДО запуска этого скрипта.
"""

import os
import sys
import threading
import zipfile
import urllib.request
import urllib.error
import subprocess
import tempfile
import time
import tkinter as tk
from tkinter import ttk, messagebox

# ─── Пути ────────────────────────────────────────────────────────────────────

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VPNClient")
BIN_DIR     = os.path.join(INSTALL_DIR, "bin")
PY_DIR      = os.path.join(INSTALL_DIR, "python")
PY_EXE      = os.path.join(PY_DIR, "python.exe")
PYW_EXE     = os.path.join(PY_DIR, "pythonw.exe")
PIP_EXE     = os.path.join(PY_DIR, "Scripts", "pip.exe")
MAIN_PY     = os.path.join(INSTALL_DIR, "main.py")
LOG_FILE    = os.path.join(os.path.expanduser("~"), "vpnclient_setup.log")

GITHUB_RAW  = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main"

SOURCE_FILES = [
    "main.py", "config.py", "requirements.txt",
    "core/__init__.py", "core/api_client.py", "core/vpn_manager.py",
    "core/protocols/__init__.py", "core/protocols/awg_manager.py",
    "core/protocols/vless_manager.py", "core/protocols/naive_manager.py",
    "ui/__init__.py", "ui/main_window.py",
]

DOWNLOADS = [
    {
        "label":  "Xray-core  (VLESS Reality)",
        "url":    "https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip",
        "entry":  "xray.exe",
        "dest":   os.path.join(BIN_DIR, "xray.exe"),
    },
    {
        "label":  "WinTUN  (TUN драйвер)",
        "url":    "https://www.wintun.net/builds/wintun-0.14.1.zip",
        "entry":  "wintun/bin/amd64/wintun.dll",
        "dest":   os.path.join(BIN_DIR, "wintun.dll"),
    },
    {
        "label":  "tun2socks",
        "url":    "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip",
        "entry":  "tun2socks-windows-amd64.exe",
        "dest":   os.path.join(BIN_DIR, "tun2socks.exe"),
    },
    {
        "label":  "NaiveProxy",
        "url":    "https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip",
        "entry":  "naive.exe",
        "dest":   os.path.join(BIN_DIR, "naive.exe"),
    },
]

AWG_MSI_URL = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"
PYTHON_ZIP_URL = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
GET_PIP_URL    = "https://bootstrap.pypa.io/get-pip.py"

TOTAL_STEPS = len(SOURCE_FILES) + len(DOWNLOADS) + 5  # py + pip + deps + awg + shortcut

# ─── Helpers ─────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    return line


def download_file(url: str, dest: str, on_progress=None):
    req = urllib.request.Request(url, headers={"User-Agent": "VPNClient-Installer/2.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done  = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done / total)


def extract_entry(zip_path: str, entry: str, dest: str):
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        filename = entry.split("/")[-1]
        match = next(
            (n for n in names
             if n == entry or n.endswith("/" + filename) or n == filename),
            None
        )
        if not match:
            raise FileNotFoundError(
                f"'{entry}' не найден в архиве.\nЕсть: {', '.join(names[:8])}"
            )
        data = zf.read(match)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)


def is_awg_installed() -> bool:
    for p in [
        r"C:\Program Files\AmneziaWG\wireguard.exe",
        r"C:\Program Files (x86)\AmneziaWG\wireguard.exe",
    ]:
        if os.path.exists(p):
            return True
    return False


def create_shortcut():
    """Ярлык на рабочем столе через PowerShell."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    link    = os.path.join(desktop, "VPN Client.lnk")
    ps = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$sc = $ws.CreateShortcut("{link}");'
        f'$sc.TargetPath = "{PYW_EXE}";'
        f'$sc.Arguments = \'"{MAIN_PY}"\';'
        f'$sc.WorkingDirectory = "{INSTALL_DIR}";'
        f'$sc.Description = "VPN Client";'
        f'$sc.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        timeout=10, capture_output=True
    )


# ─── GUI ─────────────────────────────────────────────────────────────────────

BG       = "#0F1117"
BG2      = "#161B27"
BG3      = "#1E2435"
ACCENT   = "#6C63FF"
ACCENT2  = "#8B5CF6"
GREEN    = "#22C55E"
RED      = "#EF4444"
ORANGE   = "#F59E0B"
TEXT     = "#E2E8F0"
SUBTEXT  = "#64748B"
BORDER   = "#252B3B"


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VPN Client — Установка")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.geometry("520x560")
        # Центрируем окно
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 520) // 2
        y = (self.winfo_screenheight() - 560) // 2
        self.geometry(f"520x560+{x}+{y}")
        # Запрет закрытия во время установки
        self._installing = True
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._step = 0
        self._build()
        self.after(400, self._start)

    # ── Построение UI ─────────────────────────────────────────────────────────

    def _build(self):
        # Шапка
        hdr = tk.Frame(self, bg=BG, pady=28)
        hdr.pack(fill="x")

        tk.Label(hdr, text="🔒", font=("Segoe UI Emoji", 36),
                 bg=BG, fg=ACCENT).pack()
        tk.Label(hdr, text="VPN Client",
                 font=("Segoe UI", 20, "bold"),
                 bg=BG, fg=TEXT).pack()
        tk.Label(hdr, text="VLESS Reality  ·  AmneziaWG  ·  NaiveProxy",
                 font=("Segoe UI", 9),
                 bg=BG, fg=SUBTEXT).pack(pady=(2, 0))

        # Статус-карточка
        card = tk.Frame(self, bg=BG2, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="x", padx=24, pady=(0, 18))

        inner = tk.Frame(card, bg=BG2, padx=20, pady=16)
        inner.pack(fill="x")

        # Иконка статуса
        row = tk.Frame(inner, bg=BG2)
        row.pack(fill="x")

        self.lbl_dot = tk.Label(row, text="⬤",
                                font=("Segoe UI", 14),
                                bg=BG2, fg=SUBTEXT)
        self.lbl_dot.pack(side="left")

        col = tk.Frame(row, bg=BG2)
        col.pack(side="left", padx=(10, 0))

        self.lbl_status = tk.Label(col, text="Подготовка…",
                                   font=("Segoe UI", 11, "bold"),
                                   bg=BG2, fg=TEXT, anchor="w")
        self.lbl_status.pack(fill="x")

        self.lbl_detail = tk.Label(col, text="Инициализация установщика",
                                   font=("Segoe UI", 8),
                                   bg=BG2, fg=SUBTEXT, anchor="w")
        self.lbl_detail.pack(fill="x")

        # Прогресс-бар
        pb_frame = tk.Frame(inner, bg=BG2, pady=(12, 0))
        pb_frame.pack(fill="x")
        pb_frame.pack_configure(pady=(12, 0))

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("VPN.Horizontal.TProgressbar",
                        background=ACCENT,
                        troughcolor=BG3,
                        bordercolor=BG3,
                        lightcolor=ACCENT,
                        darkcolor=ACCENT2,
                        thickness=6)

        self.pb = ttk.Progressbar(pb_frame, style="VPN.Horizontal.TProgressbar",
                                  length=456, mode="determinate")
        self.pb.pack(fill="x")

        pct_row = tk.Frame(inner, bg=BG2)
        pct_row.pack(fill="x", pady=(4, 0))
        self.lbl_pct = tk.Label(pct_row, text="0%",
                                font=("Segoe UI", 8),
                                bg=BG2, fg=SUBTEXT, anchor="e")
        self.lbl_pct.pack(side="right")

        # Шаги-индикаторы
        steps_frame = tk.Frame(self, bg=BG)
        steps_frame.pack(fill="x", padx=24, pady=(0, 16))

        step_names = [
            ("1", "Исходный код"),
            ("2", "Python"),
            ("3", "Зависимости"),
            ("4", "VPN модули"),
            ("5", "AmneziaWG"),
        ]
        self._step_labels = {}
        for i, (num, name) in enumerate(step_names):
            col_f = tk.Frame(steps_frame, bg=BG)
            col_f.pack(side="left", expand=True)

            dot = tk.Label(col_f, text="○",
                           font=("Segoe UI", 12),
                           bg=BG, fg=SUBTEXT)
            dot.pack()
            lbl = tk.Label(col_f, text=name,
                           font=("Segoe UI", 7),
                           bg=BG, fg=SUBTEXT)
            lbl.pack()
            self._step_labels[i] = (dot, lbl)

        # Лог
        log_outer = tk.Frame(self, bg=BG, padx=24)
        log_outer.pack(fill="both", expand=True, pady=(0, 16))

        log_frame = tk.Frame(log_outer, bg=BG3, bd=0,
                             highlightthickness=1, highlightbackground=BORDER)
        log_frame.pack(fill="both", expand=True)

        self.log_box = tk.Text(
            log_frame,
            font=("Consolas", 8),
            bg=BG3, fg="#3D7A3D",
            insertbackground=TEXT,
            relief="flat", bd=0,
            state="disabled", wrap="word",
            padx=10, pady=8,
        )
        sb = tk.Scrollbar(log_frame, command=self.log_box.yview,
                          bg=BG2, troughcolor=BG3, bd=0, relief="flat")
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True)

        # Кнопка запуска (скрыта до конца)
        self.btn = tk.Button(
            self,
            text="  🚀  Открыть VPN Client",
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white",
            activebackground=ACCENT2, activeforeground="white",
            relief="flat", bd=0,
            cursor="hand2",
            padx=20, pady=12,
            command=self._launch,
            state="disabled",
        )
        self.btn.pack(fill="x", padx=24, pady=(0, 20))

    # ── Обновление UI (thread-safe через after) ───────────────────────────────

    def ui(self, fn):
        self.after(0, fn)

    def log_msg(self, msg: str, color: str = "#3D7A3D"):
        line = log(msg)
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n", color)
            self.log_box.tag_configure(color, foreground=color)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.ui(_do)

    def set_status(self, title: str, detail: str = "", dot_color: str = ORANGE):
        def _do():
            self.lbl_status.configure(text=title)
            self.lbl_detail.configure(text=detail)
            self.lbl_dot.configure(fg=dot_color)
        self.ui(_do)

    def set_progress(self, done: int, total: int):
        pct = int(done / total * 100) if total else 0
        def _do():
            self.pb.configure(value=pct)
            self.lbl_pct.configure(text=f"{pct}%")
        self.ui(_do)

    def mark_step(self, idx: int, state: str):
        """state: active | done | error"""
        dot_lbl, name_lbl = self._step_labels[idx]
        cfg = {
            "active": ("◉", ORANGE, ORANGE),
            "done":   ("●", GREEN,  TEXT),
            "error":  ("●", RED,    RED),
        }.get(state, ("○", SUBTEXT, SUBTEXT))
        sym, dc, nc = cfg
        def _do():
            dot_lbl.configure(text=sym, fg=dc)
            name_lbl.configure(fg=nc)
        self.ui(_do)

    def enable_launch(self):
        def _do():
            self.btn.configure(state="normal")
            self._installing = False
        self.ui(_do)

    # ── Установка (отдельный поток) ───────────────────────────────────────────

    def _start(self):
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self):
        done = 0

        # ── 1. Исходный код ────────────────────────────────────────────────
        self.mark_step(0, "active")
        self.set_status("Скачивание VPN Client…", "Загрузка исходного кода с GitHub")
        self.log_msg("=== Исходный код ===")

        for f in SOURCE_FILES:
            dst = os.path.join(INSTALL_DIR, f.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            url = f"{GITHUB_RAW}/{f}"
            try:
                download_file(url, dst)
                self.log_msg(f"  ✓ {f}")
            except Exception as e:
                self.log_msg(f"  ✗ {f}: {e}", RED)
            done += 1
            self.set_progress(done, TOTAL_STEPS)

        self.mark_step(0, "done")

        # ── 2. Python ──────────────────────────────────────────────────────
        self.mark_step(1, "active")
        self.set_status("Python 3.12…", "Портативная версия, только для VPN Client")
        self.log_msg("=== Python 3.12 ===")

        if os.path.exists(PY_EXE):
            self.log_msg("  ✓ Python уже установлен")
        else:
            tmp = os.path.join(tempfile.gettempdir(), "py312-embed.zip")
            try:
                self.log_msg("  ⬇ Скачивание Python…")
                download_file(PYTHON_ZIP_URL, tmp)
                self.log_msg("  Распаковка…")
                os.makedirs(PY_DIR, exist_ok=True)
                with zipfile.ZipFile(tmp) as zf:
                    zf.extractall(PY_DIR)
                os.unlink(tmp)
                # Разрешаем site-packages (нужно для pip-пакетов)
                pth = next(
                    (os.path.join(PY_DIR, n)
                     for n in os.listdir(PY_DIR) if n.endswith("._pth")),
                    None
                )
                if pth:
                    with open(pth, encoding="utf-8") as f:
                        c = f.read()
                    with open(pth, "w", encoding="utf-8") as f:
                        f.write(c.replace("#import site", "import site"))
                self.log_msg("  ✓ Python 3.12 готов")
            except Exception as e:
                self.log_msg(f"  ✗ Python: {e}", RED)
                self.mark_step(1, "error")

        done += 1
        self.set_progress(done, TOTAL_STEPS)

        # pip
        if not os.path.exists(PIP_EXE):
            self.log_msg("  Установка pip…")
            gp = os.path.join(tempfile.gettempdir(), "get-pip.py")
            try:
                download_file(GET_PIP_URL, gp)
                subprocess.run([PY_EXE, gp, "--quiet"], timeout=120,
                               capture_output=True)
                os.unlink(gp)
                self.log_msg("  ✓ pip готов")
            except Exception as e:
                self.log_msg(f"  ✗ pip: {e}", RED)

        done += 1
        self.set_progress(done, TOTAL_STEPS)

        # зависимости
        self.mark_step(2, "active")
        self.set_status("Python-зависимости…", "PyQt6, requests, pyotp")
        self.log_msg("=== Зависимости ===")
        for dep in ["PyQt6", "requests", "pyotp"]:
            try:
                self.log_msg(f"  pip install {dep}…")
                subprocess.run(
                    [PIP_EXE, "install", dep, "--quiet", "--no-warn-script-location"],
                    timeout=180, capture_output=True
                )
                self.log_msg(f"  ✓ {dep}")
            except Exception as e:
                self.log_msg(f"  ✗ {dep}: {e}", RED)
        self.mark_step(1, "done")
        self.mark_step(2, "done")
        done += 1
        self.set_progress(done, TOTAL_STEPS)

        # ── 3. Бинарники VPN ──────────────────────────────────────────────
        self.mark_step(3, "active")
        self.log_msg("=== VPN модули ===")
        os.makedirs(BIN_DIR, exist_ok=True)

        for item in DOWNLOADS:
            self.set_status(f"Скачивание: {item['label']}", "VPN компоненты")
            dest = item["dest"]
            if os.path.exists(dest):
                self.log_msg(f"  ✓ {item['label']} (уже есть)")
                done += 1
                self.set_progress(done, TOTAL_STEPS)
                continue

            tmp = dest + ".tmp"
            try:
                self.log_msg(f"  ⬇ {item['label']}…")

                def _prog(frac, _d=done, _item=item):
                    self.set_progress(_d + frac, TOTAL_STEPS)

                download_file(item["url"], tmp, on_progress=_prog)
                extract_entry(tmp, item["entry"], dest)
                os.unlink(tmp)
                self.log_msg(f"  ✓ {item['label']}")
            except Exception as e:
                self.log_msg(f"  ✗ {item['label']}: {e}", RED)
                if os.path.exists(tmp):
                    try: os.unlink(tmp)
                    except: pass

            done += 1
            self.set_progress(done, TOTAL_STEPS)

        self.mark_step(3, "done")

        # ── 4. AmneziaWG ──────────────────────────────────────────────────
        self.mark_step(4, "active")
        self.set_status("AmneziaWG…", "Установка драйвера WireGuard")
        self.log_msg("=== AmneziaWG ===")

        if is_awg_installed():
            self.log_msg("  ✓ AmneziaWG уже установлен")
            self.mark_step(4, "done")
        else:
            msi = os.path.join(tempfile.gettempdir(), "amneziawg.msi")
            try:
                self.log_msg("  ⬇ Скачивание AmneziaWG…")
                download_file(AWG_MSI_URL, msi)
                self.log_msg("  Установка (тихая)…")
                subprocess.run(
                    ["msiexec", "/i", msi, "/quiet", "/norestart"],
                    timeout=120, check=True
                )
                try: os.unlink(msi)
                except: pass
                self.log_msg("  ✓ AmneziaWG установлен")
                self.mark_step(4, "done")
            except subprocess.CalledProcessError:
                self.log_msg("  ✗ Ошибка msiexec — нет прав администратора?", RED)
                self.mark_step(4, "error")
            except Exception as e:
                self.log_msg(f"  ✗ AmneziaWG: {e}", RED)
                self.mark_step(4, "error")

        done += 1
        self.set_progress(done, TOTAL_STEPS)

        # ── 5. Ярлык ──────────────────────────────────────────────────────
        self.set_status("Финальная настройка…", "Создание ярлыка на рабочем столе")
        try:
            create_shortcut()
            self.log_msg("  ✓ Ярлык 'VPN Client' создан на рабочем столе")
        except Exception as e:
            self.log_msg(f"  ✗ Ярлык: {e}", RED)

        done = TOTAL_STEPS
        self.set_progress(done, TOTAL_STEPS)

        # ── Готово ────────────────────────────────────────────────────────
        self.set_status("Установка завершена!", "Нажмите кнопку для запуска VPN Client", GREEN)
        self.log_msg("=== Готово! ===")
        self.log_msg("  Нажмите «Открыть VPN Client»")
        self.enable_launch()

    # ── Запуск VPN Client ─────────────────────────────────────────────────────

    def _launch(self):
        try:
            exe = PYW_EXE if os.path.exists(PYW_EXE) else PY_EXE
            subprocess.Popen(
                [exe, MAIN_PY],
                cwd=INSTALL_DIR,
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось запустить VPN Client:\n{e}")
            return
        self.destroy()

    def _on_close(self):
        if self._installing:
            if messagebox.askyesno("Прервать?",
                                   "Установка ещё не завершена.\nВсё равно закрыть?"):
                self.destroy()
        else:
            self.destroy()


# ─── Точка входа ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
