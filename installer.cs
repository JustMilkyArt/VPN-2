using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.5")]

static class Program
{
    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new InstallerForm());
    }
}

class InstallerForm : Form
{
    // --- UI controls ---
    private RichTextBox logBox;
    private ProgressBar progressBar;
    private Label statusLabel;
    private Button launchBtn;
    private Panel headerPanel;

    // --- Paths ---
    private static readonly string INSTALL = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "VPNClient");
    private static readonly string BIN   = Path.Combine(INSTALL, "bin");
    private static readonly string PYDIR = Path.Combine(INSTALL, "python");
    private static readonly string PYEXE = Path.Combine(PYDIR, "python.exe");
    private static readonly string PIPEXE = Path.Combine(PYDIR, "Scripts", "pip.exe");
    private static readonly string MAIN  = Path.Combine(INSTALL, "main.py");
    private static readonly string LOGFILE = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "vpnclient_setup.log");

    private static readonly string GHRAW = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main";

    private static readonly string[] SOURCES = {
        "main.py", "config.py", "requirements.txt",
        "core/__init__.py", "core/protocol_manager.py", "core/server_manager.py",
        "core/connection_manager.py", "core/process_manager.py",
        "ui/__init__.py", "ui/main_window.py", "ui/server_card.py",
        "ui/connection_dialog.py", "ui/settings_dialog.py", "ui/tray_icon.py"
    };

    private struct BinEntry {
        public string Label, Url, Entry, Dest;
        public BinEntry(string l, string u, string e, string d)
        { Label=l; Url=u; Entry=e; Dest=d; }
    }

    private static readonly BinEntry[] BINS = {
        new BinEntry("Xray-core",
            "https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip",
            "xray.exe", "xray.exe"),
        new BinEntry("WinTUN driver",
            "https://www.wintun.net/builds/wintun-0.14.1.zip",
            "wintun/bin/amd64/wintun.dll", "wintun.dll"),
        new BinEntry("tun2socks",
            "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip",
            "tun2socks-windows-amd64.exe", "tun2socks.exe"),
        new BinEntry("NaiveProxy",
            "https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip",
            "naive.exe", "naive.exe")
    };

    private static readonly string PY_URL    = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip";
    private static readonly string PIP_URL   = "https://bootstrap.pypa.io/get-pip.py";
    private static readonly string AWG_URL   = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi";

    private int totalSteps;
    private int doneSteps;

    public InstallerForm()
    {
        // 1 source-group + 1 python + 1 pip + 3 packages + 4 bins + 1 awg + 1 shortcut
        totalSteps = 1 + 1 + 1 + 3 + BINS.Length + 1 + 1;

        BuildUI();
        this.Shown += (s, e) => new Thread(RunInstall) { IsBackground = true }.Start();
    }

    // -------------------------------------------------------
    // UI
    // -------------------------------------------------------
    void BuildUI()
    {
        this.Text = "VPN Client - Setup";
        this.Size = new Size(560, 600);
        this.MinimumSize = new Size(560, 600);
        this.StartPosition = FormStartPosition.CenterScreen;
        this.BackColor = Color.FromArgb(18, 18, 30);
        this.ForeColor = Color.White;
        this.FormBorderStyle = FormBorderStyle.FixedSingle;
        this.MaximizeBox = false;

        // Header
        headerPanel = new Panel {
            Dock = DockStyle.Top, Height = 70,
            BackColor = Color.FromArgb(28, 28, 45)
        };
        var titleLbl = new Label {
            Text = "VPN Client", Font = new Font("Segoe UI", 18, FontStyle.Bold),
            ForeColor = Color.FromArgb(100, 180, 255),
            Location = new Point(20, 12), AutoSize = true
        };
        var subLbl = new Label {
            Text = "Installing components...",
            Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(150, 150, 180),
            Location = new Point(22, 44), AutoSize = true
        };
        headerPanel.Controls.Add(titleLbl);
        headerPanel.Controls.Add(subLbl);

        // Status label
        statusLabel = new Label {
            Text = "Preparing...",
            Font = new Font("Segoe UI", 9), ForeColor = Color.FromArgb(200, 200, 220),
            Location = new Point(20, 82), Size = new Size(510, 20),
            AutoSize = false
        };

        // Progress bar
        progressBar = new ProgressBar {
            Location = new Point(20, 108), Size = new Size(510, 18),
            Minimum = 0, Maximum = 100, Value = 0,
            Style = ProgressBarStyle.Continuous,
            ForeColor = Color.FromArgb(100, 180, 255)
        };

        // Log box
        logBox = new RichTextBox {
            Location = new Point(20, 140), Size = new Size(510, 360),
            BackColor = Color.FromArgb(12, 12, 22),
            ForeColor = Color.FromArgb(180, 200, 220),
            Font = new Font("Consolas", 8.5f),
            ReadOnly = true, ScrollBars = RichTextBoxScrollBars.Vertical,
            BorderStyle = BorderStyle.None, WordWrap = true
        };

        // Launch button
        launchBtn = new Button {
            Text = "Open VPN Client",
            Location = new Point(20, 514), Size = new Size(510, 38),
            Enabled = false,
            BackColor = Color.FromArgb(40, 40, 70),
            ForeColor = Color.FromArgb(120, 120, 160),
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 10, FontStyle.Bold)
        };
        launchBtn.FlatAppearance.BorderColor = Color.FromArgb(60, 60, 100);
        launchBtn.Click += (s, e) => LaunchClient();

        this.Controls.Add(headerPanel);
        this.Controls.Add(statusLabel);
        this.Controls.Add(progressBar);
        this.Controls.Add(logBox);
        this.Controls.Add(launchBtn);
    }

    // -------------------------------------------------------
    // Thread-safe UI helpers
    // -------------------------------------------------------
    void AL(string msg, Color? col = null)
    {
        string line = "[" + DateTime.Now.ToString("HH:mm:ss") + "] " + msg + "\r\n";
        File.AppendAllText(LOGFILE, line);

        if (logBox.InvokeRequired)
            logBox.Invoke(new Action(() => AppendLog(line, col ?? Color.FromArgb(180, 200, 220))));
        else
            AppendLog(line, col ?? Color.FromArgb(180, 200, 220));
    }

    void AppendLog(string line, Color col)
    {
        logBox.SelectionStart = logBox.TextLength;
        logBox.SelectionLength = 0;
        logBox.SelectionColor = col;
        logBox.AppendText(line);
        logBox.ScrollToCaret();
    }

    void SetStatus(string msg)
    {
        if (statusLabel.InvokeRequired)
            statusLabel.Invoke(new Action(() => statusLabel.Text = msg));
        else
            statusLabel.Text = msg;
    }

    void StepDone()
    {
        doneSteps++;
        int pct = (int)(100.0 * doneSteps / totalSteps);
        if (pct > 100) pct = 100;
        if (progressBar.InvokeRequired)
            progressBar.Invoke(new Action(() => progressBar.Value = pct));
        else
            progressBar.Value = pct;
    }

    void EnableLaunch()
    {
        if (launchBtn.InvokeRequired)
            launchBtn.Invoke(new Action(() => {
                launchBtn.Enabled = true;
                launchBtn.BackColor = Color.FromArgb(30, 90, 180);
                launchBtn.ForeColor = Color.White;
                launchBtn.FlatAppearance.BorderColor = Color.FromArgb(60, 140, 255);
            }));
        else {
            launchBtn.Enabled = true;
            launchBtn.BackColor = Color.FromArgb(30, 90, 180);
            launchBtn.ForeColor = Color.White;
        }
    }

    // -------------------------------------------------------
    // Install logic (background thread)
    // -------------------------------------------------------
    void RunInstall()
    {
        try
        {
            // --- 0. Create dirs ---
            Directory.CreateDirectory(INSTALL);
            Directory.CreateDirectory(BIN);
            File.AppendAllText(LOGFILE, "[" + DateTime.Now.ToString("HH:mm:ss") + "] dirs OK\r\n");

            // --- 1. Source files ---
            SetStatus("Downloading source files...");
            AL("Downloading source files from GitHub...", Color.FromArgb(100, 200, 255));
            using (var wc = new WebClient())
            {
                wc.Headers.Add("User-Agent", "VPNInstaller/1.0");
                foreach (var f in SOURCES)
                {
                    string dest = Path.Combine(INSTALL, f.Replace('/', Path.DirectorySeparatorChar));
                    Directory.CreateDirectory(Path.GetDirectoryName(dest));
                    string url = GHRAW + "/" + f;
                    try {
                        wc.DownloadFile(url, dest);
                        AL("  OK: " + f, Color.FromArgb(100, 220, 130));
                    } catch (Exception ex) {
                        AL("  WARN: " + f + " - " + ex.Message, Color.FromArgb(255, 200, 80));
                    }
                }
            }
            StepDone();

            // --- 2. Python embed ---
            SetStatus("Installing Python 3.12...");
            AL("Installing portable Python 3.12...", Color.FromArgb(100, 200, 255));
            if (!File.Exists(PYEXE))
            {
                string pyzip = Path.Combine(Path.GetTempPath(), "py312.zip");
                Download(PY_URL, pyzip);
                ZipFile.ExtractToDirectory(pyzip, PYDIR);
                // patch ._pth to allow site-packages
                foreach (var pth in Directory.GetFiles(PYDIR, "*._pth"))
                {
                    string content = File.ReadAllText(pth);
                    content = content.Replace("#import site", "import site");
                    File.WriteAllText(pth, content);
                }
                File.Delete(pyzip);
                AL("  Python extracted OK", Color.FromArgb(100, 220, 130));
            }
            else AL("  Python already present", Color.FromArgb(150, 150, 180));
            StepDone();

            // --- 3. pip ---
            SetStatus("Installing pip...");
            AL("Installing pip...", Color.FromArgb(100, 200, 255));
            if (!File.Exists(PIPEXE))
            {
                string getPip = Path.Combine(Path.GetTempPath(), "get-pip.py");
                Download(PIP_URL, getPip);
                RunCmd(PYEXE, "\"" + getPip + "\"");
                File.Delete(getPip);
                AL("  pip installed OK", Color.FromArgb(100, 220, 130));
            }
            else AL("  pip already present", Color.FromArgb(150, 150, 180));
            StepDone();

            // --- 4. Python packages ---
            foreach (var pkg in new[] { "PyQt6", "requests", "pyotp" })
            {
                SetStatus("Installing " + pkg + "...");
                AL("Installing " + pkg + "...", Color.FromArgb(100, 200, 255));
                RunCmd(PIPEXE, "install " + pkg + " --quiet");
                AL("  " + pkg + " OK", Color.FromArgb(100, 220, 130));
                StepDone();
            }

            // --- 5. VPN binaries ---
            Directory.CreateDirectory(BIN);
            foreach (var b in BINS)
            {
                SetStatus("Downloading " + b.Label + "...");
                AL("Downloading " + b.Label + "...", Color.FromArgb(100, 200, 255));
                string tmp = Path.Combine(Path.GetTempPath(), b.Label.Replace(" ", "_") + ".zip");
                Download(b.Url, tmp);
                ExtractEntry(tmp, b.Entry, Path.Combine(BIN, b.Dest));
                File.Delete(tmp);
                AL("  " + b.Label + " OK", Color.FromArgb(100, 220, 130));
                StepDone();
            }

            // --- 6. AmneziaWG ---
            SetStatus("Installing AmneziaWG...");
            AL("Installing AmneziaWG driver...", Color.FromArgb(100, 200, 255));
            string awgExe = @"C:\Program Files\AmneziaWG\wireguard.exe";
            if (!File.Exists(awgExe))
            {
                string msi = Path.Combine(Path.GetTempPath(), "amneziawg.msi");
                Download(AWG_URL, msi);
                var pi = new ProcessStartInfo("msiexec.exe",
                    "/i \"" + msi + "\" /quiet /norestart") {
                    Verb = "runas", UseShellExecute = true
                };
                var p = Process.Start(pi);
                p.WaitForExit();
                File.Delete(msi);
                AL(File.Exists(awgExe) ? "  AmneziaWG installed OK" : "  AmneziaWG install may need reboot",
                    Color.FromArgb(100, 220, 130));
            }
            else AL("  AmneziaWG already installed", Color.FromArgb(150, 150, 180));
            StepDone();

            // --- 7. Desktop shortcut ---
            SetStatus("Creating shortcut...");
            AL("Creating desktop shortcut...", Color.FromArgb(100, 200, 255));
            CreateShortcut();
            AL("  Shortcut created OK", Color.FromArgb(100, 220, 130));
            StepDone();

            // --- Done ---
            SetStatus("Installation complete!");
            AL("=== Installation complete! ===", Color.FromArgb(100, 255, 160));
            EnableLaunch();
        }
        catch (Exception ex)
        {
            AL("FATAL: " + ex.Message, Color.FromArgb(255, 80, 80));
            AL(ex.StackTrace, Color.FromArgb(200, 100, 100));
            SetStatus("Installation failed - see log");
        }
    }

    // -------------------------------------------------------
    // Helpers
    // -------------------------------------------------------
    void Download(string url, string dest)
    {
        using (var wc = new WebClient())
        {
            wc.Headers.Add("User-Agent", "VPNInstaller/1.0");
            wc.DownloadFile(url, dest);
        }
    }

    void ExtractEntry(string zipPath, string entryName, string destFile)
    {
        using (var za = ZipFile.OpenRead(zipPath))
        {
            foreach (var e in za.Entries)
            {
                // Match by suffix (handles subfolders in zip)
                if (e.FullName.EndsWith(entryName, StringComparison.OrdinalIgnoreCase)
                    || e.Name.Equals(Path.GetFileName(entryName), StringComparison.OrdinalIgnoreCase))
                {
                    e.ExtractToFile(destFile, overwrite: true);
                    return;
                }
            }
        }
        throw new Exception("Entry not found in zip: " + entryName);
    }

    void RunCmd(string exe, string args)
    {
        var pi = new ProcessStartInfo(exe, args) {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        var p = Process.Start(pi);
        p.WaitForExit();
    }

    void CreateShortcut()
    {
        // Use WScript.Shell COM object to create .lnk
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
        string lnk = Path.Combine(desktop, "VPN Client.lnk");
        Type t = Type.GetTypeFromProgID("WScript.Shell");
        dynamic sh = Activator.CreateInstance(t);
        dynamic sc = sh.CreateShortcut(lnk);
        sc.TargetPath = PYEXE;
        sc.Arguments = "\"" + MAIN + "\"";
        sc.WorkingDirectory = INSTALL;
        sc.Description = "VPN Client";
        sc.Save();
    }

    void LaunchClient()
    {
        try {
            Process.Start(PYEXE, "\"" + MAIN + "\"");
        } catch (Exception ex) {
            MessageBox.Show("Could not launch: " + ex.Message, "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
