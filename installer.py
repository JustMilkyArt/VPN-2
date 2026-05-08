"""
VPN Client Installer
- GUI на tkinter (встроен в Python, не нужен PyQt6)
- UAC запрашивается через ctypes.ShellExecute внутри Python
- Работает на любом Windows 10/11 с Python 3.8+
"""

import os, sys, subprocess, threading, zipfile, urllib.request
import time, tempfile, ctypes, logging

# ── Логирование (всегда, до GUI) ─────────────────────────────────────────────
LOG = os.path.join(os.path.expanduser("~"), "vpnclient_setup.log")
logging.basicConfig(
    filename=LOG, level=logging.DEBUG, encoding="utf-8",
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger()
log.info("=== installer.py started ===")
log.info(f"Python: {sys.version}")
log.info(f"Args: {sys.argv}")
log.info(f"Admin: {ctypes.windll.shell32.IsUserAnAdmin()}")

# ── UAC: если нет прав — перезапускаем себя через runas ─────────────────────
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    """Перезапуск с правами через ShellExecute runas — показывает UAC диалог."""
    log.info("Relaunching as admin via ShellExecute runas...")
    script = os.path.abspath(__file__)
    # ShellExecute: runas = UAC диалог
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" --admin', None, 1
    )
    log.info(f"ShellExecuteW returned: {ret}")
    sys.exit(0)

# Проверяем права при старте
if "--admin" not in sys.argv and not is_admin():
    log.info("No admin rights, requesting UAC...")
    relaunch_as_admin()

log.info("Running with admin rights, starting GUI...")

# ── GUI на tkinter ────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk

# ── Конфигурация ─────────────────────────────────────────────────────────────
INSTALL  = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VPNClient")
BIN      = os.path.join(INSTALL, "bin")
PYDIR    = os.path.join(INSTALL, "python")
PYEXE    = os.path.join(PYDIR, "python.exe")
PYWEXE   = os.path.join(PYDIR, "pythonw.exe")
PIPEXE   = os.path.join(PYDIR, "Scripts", "pip.exe")
MAINPY   = os.path.join(INSTALL, "main.py")
GHRAW    = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main"

PYZIP    = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
GETPIP   = "https://bootstrap.pypa.io/get-pip.py"
AWGMSI   = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"

SOURCES = [
    "main.py","config.py","requirements.txt",
    "core/__init__.py","core/api_client.py","core/vpn_manager.py",
    "core/protocols/__init__.py","core/protocols/awg_manager.py",
    "core/protocols/vless_manager.py","core/protocols/naive_manager.py",
    "ui/__init__.py","ui/main_window.py",
]
BINS = [
    ("Xray-core (VLESS Reality)",
     "https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip",
     "xray.exe", os.path.join(BIN,"xray.exe")),
    ("WinTUN driver",
     "https://www.wintun.net/builds/wintun-0.14.1.zip",
     "wintun/bin/amd64/wintun.dll", os.path.join(BIN,"wintun.dll")),
    ("tun2socks",
     "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip",
     "tun2socks-windows-amd64.exe", os.path.join(BIN,"tun2socks.exe")),
    ("NaiveProxy",
     "https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip",
     "naive.exe", os.path.join(BIN,"naive.exe")),
]
TOTAL = len(SOURCES) + len(BINS) + 5

# ── Download helpers ──────────────────────────────────────────────────────────
def dl(url, dest, prog_cb=None):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent":"VPNClient/4.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        total = int(r.headers.get("Content-Length",0))
        done  = 0
        with open(dest,"wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk: break
                f.write(chunk); done += len(chunk)
                if prog_cb and total:
                    prog_cb(done/total)

def unzip_entry(zpath, entry, dest):
    with zipfile.ZipFile(zpath) as z:
        fname = entry.split("/")[-1]
        m = next((n for n in z.namelist()
                   if n==entry or n.endswith("/"+fname) or n==fname), None)
        if not m: raise FileNotFoundError(f"Not in zip: {entry}")
        data = z.read(m)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest,"wb") as f: f.write(data)

def awg_installed():
    return any(os.path.exists(p) for p in [
        r"C:\Program Files\AmneziaWG\wireguard.exe",
        r"C:\Program Files (x86)\AmneziaWG\wireguard.exe",
    ])

# ── Цвета ────────────────────────────────────────────────────────────────────
BG    = "#0F1117"
BG2   = "#161B27"
BG3   = "#1E2435"
ACNT  = "#6C63FF"
GREEN = "#22C55E"
RED   = "#EF4444"
ORG   = "#F59E0B"
TEXT  = "#E2E8F0"
DIM   = "#64748B"
BORD  = "#252B3B"

# ── GUI ───────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VPN Client — Установка")
        self.configure(bg=BG)
        self.resizable(False, False)
        w, h = 500, 560
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._busy = True
        self._build()
        self.after(300, lambda: threading.Thread(target=self._install, daemon=True).start())

    # ── Построение UI ────────────────────────────────────────────────────────
    def _build(self):
        # Шапка
        tk.Label(self, text="🔒", font=("Segoe UI Emoji",38),
                 bg=BG, fg=ACNT).pack(pady=(24,0))
        tk.Label(self, text="VPN Client",
                 font=("Segoe UI",20,"bold"), bg=BG, fg=TEXT).pack()
        tk.Label(self, text="VLESS Reality  ·  AmneziaWG  ·  NaiveProxy",
                 font=("Segoe UI",9), bg=BG, fg=DIM).pack(pady=(2,14))

        # Статус-карточка
        card = tk.Frame(self, bg=BG2, highlightbackground=BORD,
                        highlightthickness=1)
        card.pack(fill="x", padx=22, pady=(0,12))
        inner = tk.Frame(card, bg=BG2); inner.pack(fill="x", padx=18, pady=14)

        top = tk.Frame(inner, bg=BG2); top.pack(fill="x")
        self.v_dot = tk.Label(top, text="⬤", font=("Segoe UI",16),
                               bg=BG2, fg=ORG)
        self.v_dot.pack(side="left")
        col = tk.Frame(top, bg=BG2); col.pack(side="left", padx=(10,0))
        self.v_title = tk.Label(col, text="Подготовка…",
                                 font=("Segoe UI",11,"bold"), bg=BG2, fg=TEXT, anchor="w")
        self.v_title.pack(fill="x")
        self.v_sub = tk.Label(col, text="Инициализация установщика",
                               font=("Segoe UI",8), bg=BG2, fg=DIM, anchor="w")
        self.v_sub.pack(fill="x")

        # Прогресс
        pb_row = tk.Frame(inner, bg=BG2); pb_row.pack(fill="x", pady=(10,0))
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("V.Horizontal.TProgressbar",
                        background=ACNT, troughcolor=BG3,
                        bordercolor=BG3, lightcolor=ACNT, darkcolor=ACNT, thickness=6)
        self.pb = ttk.Progressbar(pb_row, style="V.Horizontal.TProgressbar",
                                   length=440, mode="determinate")
        self.pb.pack(fill="x")
        self.v_pct = tk.Label(pb_row, text="0%", font=("Segoe UI",8),
                               bg=BG2, fg=DIM, anchor="e")
        self.v_pct.pack(fill="x", pady=(2,0))

        # Шаги
        sf = tk.Frame(self, bg=BG); sf.pack(fill="x", padx=22, pady=(0,10))
        self._dots = []
        for name in ["Код","Python","Пакеты","VPN","AWG"]:
            c = tk.Frame(sf, bg=BG); c.pack(side="left", expand=True)
            d = tk.Label(c, text="○", font=("Segoe UI",14), bg=BG, fg=DIM)
            d.pack()
            tk.Label(c, text=name, font=("Segoe UI",7), bg=BG, fg=DIM).pack()
            self._dots.append(d)

        # Лог
        lf = tk.Frame(self, bg=BG3, highlightbackground=BORD,
                       highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=22, pady=(0,12))
        self.log_t = tk.Text(lf, font=("Consolas",8), bg=BG3, fg="#2D7A2D",
                              relief="flat", bd=0, state="disabled",
                              wrap="word", padx=8, pady=6)
        sb = tk.Scrollbar(lf, command=self.log_t.yview,
                           bg=BG2, troughcolor=BG3, relief="flat", bd=0)
        self.log_t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_t.pack(fill="both", expand=True)

        # Кнопка
        self.btn = tk.Button(
            self, text="  🚀  Открыть VPN Client",
            font=("Segoe UI",11,"bold"),
            bg=ACNT, fg="white", activebackground="#7D75FF",
            activeforeground="white", relief="flat", bd=0,
            cursor="hand2", padx=20, pady=11,
            state="disabled", command=self._launch)
        self.btn.pack(fill="x", padx=22, pady=(0,18))

    # ── Thread-safe UI updates ────────────────────────────────────────────────
    def ui(self, fn): self.after(0, fn)

    def _log(self, msg, color="#2D7A2D"):
        log.info(msg)
        def _do():
            self.log_t.configure(state="normal")
            tag = f"c{color}"
            self.log_t.tag_configure(tag, foreground=color)
            self.log_t.insert("end", msg+"\n", tag)
            self.log_t.see("end")
            self.log_t.configure(state="disabled")
        self.ui(_do)

    def _status(self, title, sub="", dot=ORG):
        self.ui(lambda: (
            self.v_title.configure(text=title),
            self.v_sub.configure(text=sub),
            self.v_dot.configure(fg=dot)
        ))

    def _prog(self, n):
        pct = int(n/TOTAL*100)
        self.ui(lambda: (
            self.pb.configure(value=pct),
            self.v_pct.configure(text=f"{pct}%")
        ))

    def _step(self, i, state):
        sym   = {"active":"◉","done":"●","error":"●"}[state]
        color = {"active":ORG,"done":GREEN,"error":RED}[state]
        self.ui(lambda d=self._dots[i],s=sym,c=color: d.configure(text=s,fg=c))

    def _enable(self):
        self.ui(lambda: (
            self.btn.configure(state="normal"),
            self.v_dot.configure(fg=GREEN)
        ))
        self._busy = False

    # ── Установка ────────────────────────────────────────────────────────────
    def _install(self):
        n = 0

        # 1 — Исходный код
        self._step(0,"active")
        self._status("Скачивание VPN Client…","Загрузка файлов с GitHub")
        self._log("=== Исходный код ===")
        for f in SOURCES:
            dst = os.path.join(INSTALL, f.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                dl(f"{GHRAW}/{f}", dst)
                self._log(f"  ✓ {f}")
            except Exception as e:
                self._log(f"  ✗ {f}: {e}", RED)
            n+=1; self._prog(n)
        self._step(0,"done")

        # 2 — Python portable
        self._step(1,"active")
        self._status("Python 3.12…","Портативная версия для VPN Client")
        self._log("=== Python 3.12 ===")
        if os.path.exists(PYEXE):
            self._log("  ✓ Python уже установлен")
        else:
            tmp = os.path.join(tempfile.gettempdir(),"py312.zip")
            try:
                self._log("  ⬇ Скачивание…")
                dl(PYZIP, tmp)
                self._log("  Распаковка…")
                os.makedirs(PYDIR, exist_ok=True)
                with zipfile.ZipFile(tmp) as z: z.extractall(PYDIR)
                os.unlink(tmp)
                pth = next((os.path.join(PYDIR,f)
                            for f in os.listdir(PYDIR) if f.endswith("._pth")),None)
                if pth:
                    c = open(pth,encoding="utf-8").read()
                    open(pth,"w",encoding="utf-8").write(c.replace("#import site","import site"))
                self._log("  ✓ Python 3.12 готов")
            except Exception as e:
                self._log(f"  ✗ Python: {e}", RED)
                self._step(1,"error")
        n+=1; self._prog(n)

        if not os.path.exists(PIPEXE):
            self._log("  Установка pip…")
            try:
                gp = os.path.join(tempfile.gettempdir(),"get-pip.py")
                dl(GETPIP, gp)
                subprocess.run([PYEXE,gp,"--quiet"], capture_output=True, timeout=120)
                os.unlink(gp)
                self._log("  ✓ pip готов")
            except Exception as e:
                self._log(f"  ✗ pip: {e}", RED)
        n+=1; self._prog(n)

        # 3 — Зависимости
        self._step(2,"active")
        self._status("Python-зависимости…","PyQt6, requests, pyotp")
        self._log("=== Зависимости ===")
        for dep in ["PyQt6","requests","pyotp"]:
            self._log(f"  pip install {dep}…")
            try:
                subprocess.run([PIPEXE,"install",dep,"--quiet",
                                "--no-warn-script-location"],
                               capture_output=True, timeout=180)
                self._log(f"  ✓ {dep}")
            except Exception as e:
                self._log(f"  ✗ {dep}: {e}", RED)
        self._step(1,"done"); self._step(2,"done")
        n+=1; self._prog(n)

        # 4 — VPN бинарники
        self._step(3,"active")
        self._log("=== VPN модули ===")
        os.makedirs(BIN, exist_ok=True)
        for label,url,entry,dest in BINS:
            self._status(f"Скачивание: {label}…","VPN компоненты")
            if os.path.exists(dest):
                self._log(f"  ✓ {label} (уже есть)")
                n+=1; self._prog(n); continue
            tmp = dest+".tmp"
            try:
                self._log(f"  ⬇ {label}…")
                dl(url, tmp)
                unzip_entry(tmp, entry, dest)
                os.unlink(tmp)
                self._log(f"  ✓ {label}")
            except Exception as e:
                self._log(f"  ✗ {label}: {e}", RED)
                if os.path.exists(tmp):
                    try: os.unlink(tmp)
                    except: pass
            n+=1; self._prog(n)
        self._step(3,"done")

        # 5 — AmneziaWG
        self._step(4,"active")
        self._status("AmneziaWG…","Установка драйвера WireGuard")
        self._log("=== AmneziaWG ===")
        if awg_installed():
            self._log("  ✓ AmneziaWG уже установлен")
            self._step(4,"done")
        else:
            msi = os.path.join(tempfile.gettempdir(),"awg.msi")
            try:
                self._log("  ⬇ Скачивание AmneziaWG…")
                dl(AWGMSI, msi)
                self._log("  Установка…")
                r = subprocess.run(
                    ["msiexec","/i",msi,"/quiet","/norestart"],
                    timeout=120)
                try: os.unlink(msi)
                except: pass
                if awg_installed():
                    self._log("  ✓ AmneziaWG установлен")
                    self._step(4,"done")
                else:
                    self._log(f"  ✗ msiexec вернул: {r.returncode}", RED)
                    self._step(4,"error")
            except Exception as e:
                self._log(f"  ✗ AmneziaWG: {e}", RED)
                self._step(4,"error")
        n+=1; self._prog(n)

        # Ярлык
        self._status("Создание ярлыка…","")
        try:
            desk = os.path.join(os.path.expanduser("~"),"Desktop")
            link = os.path.join(desk,"VPN Client.lnk")
            exe  = PYWEXE if os.path.exists(PYWEXE) else PYEXE
            ps   = (f'$ws=New-Object -ComObject WScript.Shell;'
                    f'$sc=$ws.CreateShortcut("{link}");'
                    f'$sc.TargetPath="{exe}";'
                    f'$sc.Arguments=\'"{MAINPY}"\';'
                    f'$sc.WorkingDirectory="{INSTALL}";'
                    f'$sc.Save()')
            subprocess.run(["powershell","-NoProfile","-ExecutionPolicy",
                            "Bypass","-Command",ps],
                           capture_output=True, timeout=10)
            self._log("  ✓ Ярлык на рабочем столе создан")
        except Exception as e:
            self._log(f"  ✗ Ярлык: {e}", RED)

        self._prog(TOTAL)
        self._status("Установка завершена!",
                     "Нажмите кнопку для запуска VPN Client", GREEN)
        self._log("=== Готово! ===")
        self._enable()

    # ── Запуск ───────────────────────────────────────────────────────────────
    def _launch(self):
        try:
            exe = PYWEXE if os.path.exists(PYWEXE) else PYEXE
            subprocess.Popen([exe, MAINPY], cwd=INSTALL,
                             creationflags=0x00000008)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка", f"Не удалось запустить:\n{e}")
            return
        self.destroy()

    def _on_close(self):
        if self._busy:
            import tkinter.messagebox as mb
            if not mb.askyesno("Прервать?","Установка ещё не завершена. Закрыть?"):
                return
        self.destroy()

if __name__ == "__main__":
    log.info("Creating App window...")
    try:
        App().mainloop()
    except Exception as e:
        log.exception(f"App crashed: {e}")
