# VPN Client Installer — Windows Forms GUI
# PowerShell 5+, встроен в Windows 10/11

# ── Сначала — перехват ЛЮБОЙ ошибки до GUI ───────────────────────────────────
trap {
    $msg = "FATAL: $_"
    try { Add-Content "$env:USERPROFILE\vpnclient_setup.log" $msg -EA SilentlyContinue } catch {}
    try {
        Add-Type -AssemblyName System.Windows.Forms -EA SilentlyContinue
        [System.Windows.Forms.MessageBox]::Show(
            "Ошибка установщика:`n$_`n`nЛог: $env:USERPROFILE\vpnclient_setup.log",
            "VPN Client — Ошибка", 0, 16)
    } catch {}
    exit 1
}

$ErrorActionPreference = 'Stop'
$LOG = "$env:USERPROFILE\vpnclient_setup.log"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function L($m) {
    $line = "[$(Get-Date -f 'HH:mm:ss')] $m"
    Add-Content $LOG $line -EA SilentlyContinue
    Write-Host $line
}

L "=== installer.ps1 started ==="
L "PS Version: $($PSVersionTable.PSVersion)"
L "User: $env:USERNAME"
L "Dir: $(Get-Location)"

# ── Пути ─────────────────────────────────────────────────────────────────────
$INSTALL = "$env:LOCALAPPDATA\VPNClient"
$BIN     = "$INSTALL\bin"
$PYDIR   = "$INSTALL\python"
$PYEXE   = "$PYDIR\python.exe"
$PYWEXE  = "$PYDIR\pythonw.exe"
$PIPEXE  = "$PYDIR\Scripts\pip.exe"
$MAINPY  = "$INSTALL\main.py"
$GHRAW   = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main"

$SOURCES = @(
    "main.py","config.py","requirements.txt",
    "core/__init__.py","core/api_client.py","core/vpn_manager.py",
    "core/protocols/__init__.py","core/protocols/awg_manager.py",
    "core/protocols/vless_manager.py","core/protocols/naive_manager.py",
    "ui/__init__.py","ui/main_window.py"
)
$BINS = @(
    @{L="Xray-core (VLESS)"; U="https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip";                                                                  E="xray.exe";                    D="$BIN\xray.exe"},
    @{L="WinTUN driver";     U="https://www.wintun.net/builds/wintun-0.14.1.zip";                                                                                                    E="wintun/bin/amd64/wintun.dll"; D="$BIN\wintun.dll"},
    @{L="tun2socks";         U="https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip";                                                       E="tun2socks-windows-amd64.exe"; D="$BIN\tun2socks.exe"},
    @{L="NaiveProxy";        U="https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip";                                 E="naive.exe";                   D="$BIN\naive.exe"}
)
$AWGMSI  = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"
$PYZIP   = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
$GETPIP  = "https://bootstrap.pypa.io/get-pip.py"
$TOTAL   = $SOURCES.Count + $BINS.Count + 5

# ── Helpers ───────────────────────────────────────────────────────────────────
function DL($url, $dest) {
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $wc = New-Object Net.WebClient
    $wc.Headers.Add("User-Agent", "VPNClient/4.0")
    $wc.DownloadFile($url, $dest)
    $wc.Dispose()
}

function UnzipEntry($zip, $entry, $dest) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z     = [IO.Compression.ZipFile]::OpenRead($zip)
    $fname = ($entry -split '/')[-1]
    $e     = $z.Entries | Where-Object { $_.FullName -eq $entry -or $_.Name -eq $fname } | Select-Object -First 1
    if (-not $e) { $z.Dispose(); throw "Not in zip: $entry" }
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
    $z.Dispose()
}

function AwgOk { Test-Path "C:\Program Files\AmneziaWG\wireguard.exe" }

# ── Windows Forms GUI ─────────────────────────────────────────────────────────
L "Loading Windows Forms..."
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$form          = New-Object Windows.Forms.Form
$form.Text     = "VPN Client — Установка"
$form.Size     = New-Object Drawing.Size(500, 560)
$form.StartPosition = "CenterScreen"
$form.BackColor     = [Drawing.Color]::FromArgb(15, 17, 23)
$form.ForeColor     = [Drawing.Color]::FromArgb(226, 232, 240)
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox   = $false
$form.Font          = New-Object Drawing.Font("Segoe UI", 9)

L "Form created, adding controls..."

# Иконка (замок через emoji label)
$lblIcon          = New-Object Windows.Forms.Label
$lblIcon.Text     = "🔒"
$lblIcon.Font     = New-Object Drawing.Font("Segoe UI Emoji", 28)
$lblIcon.Size     = New-Object Drawing.Size(460, 50)
$lblIcon.Location = New-Object Drawing.Point(20, 18)
$lblIcon.TextAlign = "MiddleCenter"
$lblIcon.BackColor = [Drawing.Color]::Transparent
$lblIcon.ForeColor = [Drawing.Color]::FromArgb(108, 99, 255)
$form.Controls.Add($lblIcon)

# Заголовок
$lblTitle          = New-Object Windows.Forms.Label
$lblTitle.Text     = "VPN Client"
$lblTitle.Font     = New-Object Drawing.Font("Segoe UI", 16, [Drawing.FontStyle]::Bold)
$lblTitle.Size     = New-Object Drawing.Size(460, 30)
$lblTitle.Location = New-Object Drawing.Point(20, 72)
$lblTitle.TextAlign = "MiddleCenter"
$lblTitle.BackColor = [Drawing.Color]::Transparent
$lblTitle.ForeColor = [Drawing.Color]::White
$form.Controls.Add($lblTitle)

# Подзаголовок
$lblSub          = New-Object Windows.Forms.Label
$lblSub.Text     = "VLESS Reality  ·  AmneziaWG  ·  NaiveProxy"
$lblSub.Font     = New-Object Drawing.Font("Segoe UI", 8)
$lblSub.Size     = New-Object Drawing.Size(460, 20)
$lblSub.Location = New-Object Drawing.Point(20, 104)
$lblSub.TextAlign = "MiddleCenter"
$lblSub.BackColor = [Drawing.Color]::Transparent
$lblSub.ForeColor = [Drawing.Color]::FromArgb(100, 116, 139)
$form.Controls.Add($lblSub)

# Карточка статуса
$card          = New-Object Windows.Forms.Panel
$card.Size     = New-Object Drawing.Size(454, 80)
$card.Location = New-Object Drawing.Point(23, 132)
$card.BackColor = [Drawing.Color]::FromArgb(22, 27, 39)
$form.Controls.Add($card)

$lblStatus          = New-Object Windows.Forms.Label
$lblStatus.Text     = "Подготовка..."
$lblStatus.Font     = New-Object Drawing.Font("Segoe UI", 10, [Drawing.FontStyle]::Bold)
$lblStatus.Size     = New-Object Drawing.Size(410, 22)
$lblStatus.Location = New-Object Drawing.Point(16, 10)
$lblStatus.BackColor = [Drawing.Color]::Transparent
$lblStatus.ForeColor = [Drawing.Color]::White
$card.Controls.Add($lblStatus)

$lblDetail          = New-Object Windows.Forms.Label
$lblDetail.Text     = "Инициализация..."
$lblDetail.Font     = New-Object Drawing.Font("Segoe UI", 8)
$lblDetail.Size     = New-Object Drawing.Size(410, 18)
$lblDetail.Location = New-Object Drawing.Point(16, 34)
$lblDetail.BackColor = [Drawing.Color]::Transparent
$lblDetail.ForeColor = [Drawing.Color]::FromArgb(100, 116, 139)
$card.Controls.Add($lblDetail)

# Прогресс-бар
$pb          = New-Object Windows.Forms.ProgressBar
$pb.Size     = New-Object Drawing.Size(410, 10)
$pb.Location = New-Object Drawing.Point(16, 58)
$pb.Maximum  = 100
$pb.Value    = 0
$pb.Style    = "Continuous"
$card.Controls.Add($pb)

# Процент
$lblPct          = New-Object Windows.Forms.Label
$lblPct.Text     = "0%"
$lblPct.Font     = New-Object Drawing.Font("Segoe UI", 7)
$lblPct.Size     = New-Object Drawing.Size(50, 16)
$lblPct.Location = New-Object Drawing.Point(400, 218)
$lblPct.BackColor = [Drawing.Color]::Transparent
$lblPct.ForeColor = [Drawing.Color]::FromArgb(100, 116, 139)
$lblPct.TextAlign = "MiddleRight"
$form.Controls.Add($lblPct)

# Шаги
$stepNames = @("Код","Python","Пакеты","VPN","AWG")
$stepLabels = @()
$stepDots   = @()
$sx = 23
for ($i = 0; $i -lt 5; $i++) {
    $dot          = New-Object Windows.Forms.Label
    $dot.Text     = "○"
    $dot.Font     = New-Object Drawing.Font("Segoe UI", 12)
    $dot.Size     = New-Object Drawing.Size(88, 22)
    $dot.Location = New-Object Drawing.Point($sx + ($i*88), 230)
    $dot.TextAlign = "MiddleCenter"
    $dot.BackColor = [Drawing.Color]::Transparent
    $dot.ForeColor = [Drawing.Color]::FromArgb(100, 116, 139)
    $form.Controls.Add($dot)
    $stepDots += $dot

    $lbl          = New-Object Windows.Forms.Label
    $lbl.Text     = $stepNames[$i]
    $lbl.Font     = New-Object Drawing.Font("Segoe UI", 7)
    $lbl.Size     = New-Object Drawing.Size(88, 16)
    $lbl.Location = New-Object Drawing.Point($sx + ($i*88), 252)
    $lbl.TextAlign = "MiddleCenter"
    $lbl.BackColor = [Drawing.Color]::Transparent
    $lbl.ForeColor = [Drawing.Color]::FromArgb(100, 116, 139)
    $form.Controls.Add($lbl)
    $stepLabels += $lbl
}

# Лог
$logBox              = New-Object Windows.Forms.RichTextBox
$logBox.Size         = New-Object Drawing.Size(454, 190)
$logBox.Location     = New-Object Drawing.Point(23, 276)
$logBox.BackColor    = [Drawing.Color]::FromArgb(13, 16, 24)
$logBox.ForeColor    = [Drawing.Color]::FromArgb(45, 122, 45)
$logBox.Font         = New-Object Drawing.Font("Consolas", 8)
$logBox.ReadOnly     = $true
$logBox.BorderStyle  = "None"
$logBox.ScrollBars   = "Vertical"
$form.Controls.Add($logBox)

# Кнопка запуска
$btn              = New-Object Windows.Forms.Button
$btn.Text         = "🚀  Открыть VPN Client"
$btn.Font         = New-Object Drawing.Font("Segoe UI", 10, [Drawing.FontStyle]::Bold)
$btn.Size         = New-Object Drawing.Size(454, 44)
$btn.Location     = New-Object Drawing.Point(23, 478)
$btn.BackColor    = [Drawing.Color]::FromArgb(108, 99, 255)
$btn.ForeColor    = [Drawing.Color]::White
$btn.FlatStyle    = "Flat"
$btn.FlatAppearance.BorderSize = 0
$btn.Enabled      = $false
$btn.Cursor       = [Windows.Forms.Cursors]::Hand
$form.Controls.Add($btn)

L "All controls added — showing window next"

# ── UI helpers (вызов из фонового потока) ────────────────────────────────────
function UI([scriptblock]$sb) {
    $form.Invoke([Action]$sb)
}

$script:n = 0

function SetStatus($title, $detail = "") {
    UI { $lblStatus.Text = $title; $lblDetail.Text = $detail }
}
function AddLog($msg, [Drawing.Color]$color = [Drawing.Color]::FromArgb(45,122,45)) {
    L $msg
    UI {
        $logBox.SelectionStart  = $logBox.TextLength
        $logBox.SelectionLength = 0
        $logBox.SelectionColor  = $color
        $logBox.AppendText("$msg`n")
        $logBox.ScrollToCaret()
    }
}
function SetStep($i, $state) {
    $sym   = @{active="◉"; done="●"; error="●"}[$state]
    $color = @{
        active = [Drawing.Color]::FromArgb(245,158,11)
        done   = [Drawing.Color]::FromArgb(34,197,94)
        error  = [Drawing.Color]::FromArgb(239,68,68)
    }[$state]
    UI { $stepDots[$i].Text = $sym; $stepDots[$i].ForeColor = $color }
}
function SetProg($done) {
    $pct = [int]($done / $TOTAL * 100)
    UI { $pb.Value = [Math]::Min($pct,100); $lblPct.Text = "$pct%" }
}
function Done() {
    UI {
        $btn.Enabled   = $true
        $lblStatus.Text = "Установка завершена!"
        $lblDetail.Text = "Нажмите кнопку для запуска"
        $lblStatus.ForeColor = [Drawing.Color]::FromArgb(34,197,94)
    }
}

# ── Кнопка запуска ───────────────────────────────────────────────────────────
$btn.Add_Click({
    $exe = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
    Start-Process $exe -ArgumentList "`"$MAINPY`"" -WorkingDirectory $INSTALL
    $form.Close()
})

# ── Установка (фоновый поток) ────────────────────────────────────────────────
$job = [System.Threading.Thread]::new([System.Threading.ThreadStart]{
    try {
        $n = 0

        # 1 — Исходный код
        SetStep 0 "active"
        SetStatus "Скачивание VPN Client..." "Загрузка файлов с GitHub"
        AddLog "=== Исходный код ==="
        New-Item -ItemType Directory -Force -Path $INSTALL | Out-Null
        foreach ($f in $SOURCES) {
            $dst = "$INSTALL\$($f -replace '/','\\')"
            $dir = Split-Path $dst
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            try { DL "$GHRAW/$f" $dst; AddLog "  OK: $f" }
            catch { AddLog "  !! $f : $_" ([Drawing.Color]::FromArgb(239,68,68)) }
            $n++; SetProg $n
        }
        SetStep 0 "done"

        # 2 — Python
        SetStep 1 "active"
        SetStatus "Python 3.12..." "Скачивание портативной версии"
        AddLog "=== Python 3.12 ==="
        if (Test-Path $PYEXE) {
            AddLog "  OK: Python уже установлен"
        } else {
            try {
                AddLog "  Скачивание Python 3.12..."
                $pz = "$env:TEMP\py312.zip"
                DL $PYZIP $pz
                AddLog "  Распаковка..."
                New-Item -ItemType Directory -Force -Path $PYDIR | Out-Null
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                [IO.Compression.ZipFile]::ExtractToDirectory($pz, $PYDIR)
                Remove-Item $pz -Force -EA SilentlyContinue
                $pth = Get-ChildItem $PYDIR -Filter "*._pth" | Select-Object -First 1
                if ($pth) {
                    (Get-Content $pth.FullName) -replace '#import site','import site' |
                        Set-Content $pth.FullName
                }
                AddLog "  OK: Python 3.12 готов"
            } catch {
                AddLog "  !! Python: $_" ([Drawing.Color]::FromArgb(239,68,68))
                SetStep 1 "error"
            }
        }
        $n++; SetProg $n

        # pip
        if (-not (Test-Path $PIPEXE)) {
            try {
                AddLog "  Установка pip..."
                $gp = "$env:TEMP\get-pip.py"
                DL $GETPIP $gp
                & $PYEXE $gp "--quiet" 2>$null
                Remove-Item $gp -Force -EA SilentlyContinue
                AddLog "  OK: pip"
            } catch { AddLog "  !! pip: $_" ([Drawing.Color]::FromArgb(239,68,68)) }
        }
        $n++; SetProg $n

        # Зависимости
        SetStep 2 "active"
        SetStatus "Зависимости..." "PyQt6, requests, pyotp"
        AddLog "=== Зависимости ==="
        foreach ($dep in @("PyQt6","requests","pyotp")) {
            AddLog "  pip install $dep..."
            try { & $PIPEXE install $dep "--quiet" "--no-warn-script-location" 2>$null; AddLog "  OK: $dep" }
            catch { AddLog "  !! $dep : $_" ([Drawing.Color]::FromArgb(239,68,68)) }
        }
        SetStep 1 "done"; SetStep 2 "done"
        $n++; SetProg $n

        # 3 — Бинарники
        SetStep 3 "active"
        AddLog "=== VPN модули ==="
        New-Item -ItemType Directory -Force -Path $BIN | Out-Null
        foreach ($b in $BINS) {
            SetStatus "Скачивание: $($b.L)..." "VPN компоненты"
            if (Test-Path $b.D) {
                AddLog "  OK: $($b.L) (уже есть)"
                $n++; SetProg $n; continue
            }
            $tmp = "$env:TEMP\vpnbin_$([IO.Path]::GetRandomFileName()).zip"
            try {
                AddLog "  Скачивание $($b.L)..."
                DL $b.U $tmp
                UnzipEntry $tmp $b.E $b.D
                Remove-Item $tmp -Force -EA SilentlyContinue
                AddLog "  OK: $($b.L)"
            } catch {
                AddLog "  !! $($b.L): $_" ([Drawing.Color]::FromArgb(239,68,68))
                Remove-Item $tmp -Force -EA SilentlyContinue
            }
            $n++; SetProg $n
        }
        SetStep 3 "done"

        # 4 — AmneziaWG
        SetStep 4 "active"
        SetStatus "AmneziaWG..." "Установка драйвера WireGuard"
        AddLog "=== AmneziaWG ==="
        if (AwgOk) {
            AddLog "  OK: AmneziaWG уже установлен"
            SetStep 4 "done"
        } else {
            $msi = "$env:TEMP\awg.msi"
            try {
                AddLog "  Скачивание AmneziaWG..."
                DL $AWGMSI $msi
                AddLog "  Установка..."
                $p = Start-Process msiexec -ArgumentList "/i `"$msi`" /quiet /norestart" -Wait -PassThru
                Remove-Item $msi -Force -EA SilentlyContinue
                if (AwgOk) { AddLog "  OK: AmneziaWG установлен"; SetStep 4 "done" }
                else        { AddLog "  !! msiexec: $($p.ExitCode)" ([Drawing.Color]::FromArgb(239,68,68)); SetStep 4 "error" }
            } catch {
                AddLog "  !! AmneziaWG: $_" ([Drawing.Color]::FromArgb(239,68,68))
                SetStep 4 "error"
            }
        }
        $n++; SetProg $n

        # Ярлык
        try {
            $link = "$env:USERPROFILE\Desktop\VPN Client.lnk"
            $exe  = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
            $ws   = New-Object -ComObject WScript.Shell
            $sc   = $ws.CreateShortcut($link)
            $sc.TargetPath       = $exe
            $sc.Arguments        = "`"$MAINPY`""
            $sc.WorkingDirectory = $INSTALL
            $sc.Description      = "VPN Client"
            $sc.Save()
            AddLog "  OK: Ярлык на рабочем столе"
        } catch { AddLog "  !! Ярлык: $_" ([Drawing.Color]::FromArgb(239,68,68)) }

        SetProg $TOTAL
        AddLog "=== Готово! Нажмите кнопку ==="
        Done

    } catch {
        L "FATAL: $_"
        AddLog "FATAL ERROR: $_" ([Drawing.Color]::FromArgb(239,68,68))
        UI { $lblStatus.Text = "Ошибка установки"; $lblDetail.Text = "См. лог: $LOG" }
    }
})
$job.IsBackground = $true

L "Starting install thread..."
$form.Add_Shown({ $job.Start() })

L "Showing form..."
try {
    [Windows.Forms.Application]::Run($form)
} catch {
    L "Form crashed: $_"
}
L "Form closed."
