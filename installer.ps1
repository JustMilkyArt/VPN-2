# VPN Client Installer - PowerShell 5+ WinForms

$ErrorActionPreference = 'Stop'
$LOG = "$env:USERPROFILE\vpnclient_setup.log"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function L($m) {
    Add-Content $LOG "[$(Get-Date -f 'HH:mm:ss')] $m" -EA SilentlyContinue
}

L "=== installer.ps1 started ==="
L "PS: $($PSVersionTable.PSVersion)"

$INSTALL = "$env:LOCALAPPDATA\VPNClient"
$BIN     = "$INSTALL\bin"
$PYDIR   = "$INSTALL\python"
$PYEXE   = "$PYDIR\python.exe"
$PYWEXE  = "$PYDIR\pythonw.exe"
$PIPEXE  = "$PYDIR\Scripts\pip.exe"
$MAINPY  = "$INSTALL\main.py"
$GHRAW   = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main"
$PYZIP   = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
$GETPIP  = "https://bootstrap.pypa.io/get-pip.py"
$AWGMSI  = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"

$SOURCES = @(
    "main.py","config.py","requirements.txt",
    "core/__init__.py","core/api_client.py","core/vpn_manager.py",
    "core/protocols/__init__.py","core/protocols/awg_manager.py",
    "core/protocols/vless_manager.py","core/protocols/naive_manager.py",
    "ui/__init__.py","ui/main_window.py"
)
$BINS = @(
    @{N="Xray-core"; U="https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip"; E="xray.exe"; D="$BIN\xray.exe"},
    @{N="WinTUN"; U="https://www.wintun.net/builds/wintun-0.14.1.zip"; E="wintun/bin/amd64/wintun.dll"; D="$BIN\wintun.dll"},
    @{N="tun2socks"; U="https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip"; E="tun2socks-windows-amd64.exe"; D="$BIN\tun2socks.exe"},
    @{N="NaiveProxy"; U="https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip"; E="naive.exe"; D="$BIN\naive.exe"}
)
$TOTAL = $SOURCES.Count + $BINS.Count + 5

function DL($url, $dest) {
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $wc = New-Object Net.WebClient
    $wc.Headers.Add("User-Agent","VPNClient/7")
    $wc.DownloadFile($url, $dest)
    $wc.Dispose()
}

function UZE($zip, $entry, $dest) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($zip)
    $fname = ($entry -split '/')[-1]
    $e = $z.Entries | Where-Object { $_.FullName -eq $entry -or $_.Name -eq $fname } | Select-Object -First 1
    if (-not $e) { $z.Dispose(); throw "Not in zip: $entry" }
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
    $z.Dispose()
}

L "Loading WinForms..."
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Drawing")
L "WinForms loaded"

[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text            = "VPN Client - Setup"
$form.Width           = 480
$form.Height          = 520
$form.StartPosition   = "CenterScreen"
$form.BackColor       = [System.Drawing.Color]::FromArgb(18, 20, 28)
$form.ForeColor       = [System.Drawing.Color]::White
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox     = $false
$form.Font            = New-Object System.Drawing.Font("Segoe UI", 9)

$t = New-Object System.Windows.Forms.Label
$t.Text = "VPN Client"; $t.Width = 440; $t.Height = 34
$t.Left = 20; $t.Top = 18; $t.TextAlign = "MiddleCenter"
$t.Font = New-Object System.Drawing.Font("Segoe UI", 17, [System.Drawing.FontStyle]::Bold)
$t.ForeColor = [System.Drawing.Color]::White
$t.BackColor = [System.Drawing.Color]::Transparent
$form.Controls.Add($t)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = "VLESS Reality  |  AmneziaWG  |  NaiveProxy"
$sub.Width = 440; $sub.Height = 18; $sub.Left = 20; $sub.Top = 56
$sub.TextAlign = "MiddleCenter"
$sub.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$sub.ForeColor = [System.Drawing.Color]::FromArgb(120, 130, 150)
$sub.BackColor = [System.Drawing.Color]::Transparent
$form.Controls.Add($sub)

$card = New-Object System.Windows.Forms.Panel
$card.Width = 440; $card.Height = 72; $card.Left = 20; $card.Top = 84
$card.BackColor = [System.Drawing.Color]::FromArgb(26, 30, 42)
$form.Controls.Add($card)

$lblS = New-Object System.Windows.Forms.Label
$lblS.Text = "Preparing..."; $lblS.Width = 400; $lblS.Height = 22
$lblS.Left = 16; $lblS.Top = 8
$lblS.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$lblS.ForeColor = [System.Drawing.Color]::White
$lblS.BackColor = [System.Drawing.Color]::Transparent
$card.Controls.Add($lblS)

$lblD = New-Object System.Windows.Forms.Label
$lblD.Text = "Starting..."; $lblD.Width = 400; $lblD.Height = 18
$lblD.Left = 16; $lblD.Top = 34
$lblD.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$lblD.ForeColor = [System.Drawing.Color]::FromArgb(120, 130, 150)
$lblD.BackColor = [System.Drawing.Color]::Transparent
$card.Controls.Add($lblD)

$pb = New-Object System.Windows.Forms.ProgressBar
$pb.Width = 400; $pb.Height = 10; $pb.Left = 16; $pb.Top = 56
$pb.Maximum = 100; $pb.Value = 0; $pb.Style = "Continuous"
$card.Controls.Add($pb)

$stepNames = @("Code","Python","Deps","VPN","AWG")
$dots = @()
for ($i = 0; $i -lt 5; $i++) {
    $d = New-Object System.Windows.Forms.Label
    $d.Text = "o"; $d.Width = 88; $d.Height = 22
    $d.Left = 20 + $i*88; $d.Top = 170
    $d.TextAlign = "MiddleCenter"
    $d.Font = New-Object System.Drawing.Font("Segoe UI", 11)
    $d.BackColor = [System.Drawing.Color]::Transparent
    $d.ForeColor = [System.Drawing.Color]::FromArgb(80, 90, 110)
    $form.Controls.Add($d); $dots += $d

    $n2 = New-Object System.Windows.Forms.Label
    $n2.Text = $stepNames[$i]; $n2.Width = 88; $n2.Height = 16
    $n2.Left = 20 + $i*88; $n2.Top = 192
    $n2.TextAlign = "MiddleCenter"
    $n2.Font = New-Object System.Drawing.Font("Segoe UI", 7)
    $n2.BackColor = [System.Drawing.Color]::Transparent
    $n2.ForeColor = [System.Drawing.Color]::FromArgb(80, 90, 110)
    $form.Controls.Add($n2)
}

$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.Width = 440; $rtb.Height = 200; $rtb.Left = 20; $rtb.Top = 218
$rtb.BackColor = [System.Drawing.Color]::FromArgb(12, 14, 20)
$rtb.ForeColor = [System.Drawing.Color]::FromArgb(50, 200, 80)
$rtb.Font = New-Object System.Drawing.Font("Consolas", 8)
$rtb.ReadOnly = $true; $rtb.BorderStyle = "None"; $rtb.ScrollBars = "Vertical"
$form.Controls.Add($rtb)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = "Open VPN Client"; $btn.Width = 440; $btn.Height = 42
$btn.Left = 20; $btn.Top = 432
$btn.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$btn.BackColor = [System.Drawing.Color]::FromArgb(99, 90, 240)
$btn.ForeColor = [System.Drawing.Color]::White
$btn.FlatStyle = "Flat"; $btn.FlatAppearance.BorderSize = 0
$btn.Enabled = $false; $btn.Cursor = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btn)

L "Form built OK"

# Colors
$RED   = [System.Drawing.Color]::FromArgb(239, 68, 68)
$GREEN = [System.Drawing.Color]::FromArgb(50, 200, 80)
$AMBER = [System.Drawing.Color]::FromArgb(245, 158, 11)

# --- UI helpers: safe Invoke only after handle is created ---
function UI([scriptblock]$sb) {
    if ($form.IsHandleCreated) {
        $form.Invoke([System.Action]$sb) | Out-Null
    }
}

function SS($title, $detail) {
    UI { $lblS.Text = $title; $lblD.Text = $detail }
}

function AL($msg, $col) {
    L $msg
    if (-not $col) { $col = $GREEN }
    UI {
        $rtb.SelectionStart = $rtb.TextLength
        $rtb.SelectionLength = 0
        $rtb.SelectionColor = $col
        $rtb.AppendText("$msg`n")
        $rtb.ScrollToCaret()
    }
}

function SP($done) {
    $pct = [int]($done / $TOTAL * 100)
    UI { $pb.Value = [Math]::Min($pct, 100) }
}

function STEP($i, $s) {
    $sym = if ($s -eq "done") { "*" } elseif ($s -eq "err") { "!" } else { ">" }
    $col = if ($s -eq "done") { [System.Drawing.Color]::FromArgb(34,197,94) } `
      elseif ($s -eq "err")  { $RED } else { $AMBER }
    UI { $dots[$i].Text = $sym; $dots[$i].ForeColor = $col }
}

$btn.Add_Click({
    $exe = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
    Start-Process $exe -ArgumentList "`"$MAINPY`"" -WorkingDirectory $INSTALL
    $form.Close()
})

# --- Background install thread ---
$job = [System.Threading.Thread]::new([System.Threading.ThreadStart]{
    try {
        # Wait for form handle to be created before any UI calls
        $waited = 0
        while (-not $form.IsHandleCreated -and $waited -lt 5000) {
            [System.Threading.Thread]::Sleep(100)
            $waited += 100
        }
        L "Handle ready after ${waited}ms"

        # Small extra pause to let the message loop start
        [System.Threading.Thread]::Sleep(300)

        $n = 0

        # Step 1: Source code
        STEP 0 "act"
        SS "Downloading source code..." "GitHub"
        AL "=== Source code ==="
        New-Item -ItemType Directory -Force -Path $INSTALL | Out-Null
        foreach ($f in $SOURCES) {
            $dst = "$INSTALL\$($f -replace '/','\\')"
            $dir = Split-Path $dst
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            try   { DL "$GHRAW/$f" $dst; AL "  OK $f" }
            catch { AL "  FAIL $f : $_" $RED }
            $n++; SP $n
        }
        STEP 0 "done"

        # Step 2: Python
        STEP 1 "act"
        SS "Python 3.12..." "Downloading portable"
        AL "=== Python 3.12 ==="
        if (Test-Path $PYEXE) {
            AL "  OK already installed"
        } else {
            $pz = "$env:TEMP\py312.zip"
            AL "  Downloading Python 3.12..."
            DL $PYZIP $pz
            AL "  Extracting..."
            New-Item -ItemType Directory -Force -Path $PYDIR | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($pz, $PYDIR)
            Remove-Item $pz -Force -EA SilentlyContinue
            $pth = Get-ChildItem $PYDIR -Filter "*._pth" | Select-Object -First 1
            if ($pth) {
                (Get-Content $pth.FullName) -replace '#import site','import site' |
                    Set-Content $pth.FullName
            }
            AL "  OK Python ready"
        }
        $n++; SP $n

        if (-not (Test-Path $PIPEXE)) {
            AL "  Installing pip..."
            $gp = "$env:TEMP\get-pip.py"
            DL $GETPIP $gp
            & $PYEXE $gp "--quiet" 2>$null
            Remove-Item $gp -Force -EA SilentlyContinue
            AL "  OK pip"
        }
        $n++; SP $n

        # Step 3: Dependencies
        STEP 2 "act"
        SS "Dependencies..." "PyQt6 requests pyotp"
        AL "=== Dependencies ==="
        foreach ($dep in @("PyQt6","requests","pyotp")) {
            AL "  pip install $dep..."
            try   { & $PIPEXE install $dep "--quiet" "--no-warn-script-location" 2>$null; AL "  OK $dep" }
            catch { AL "  FAIL $dep : $_" $RED }
        }
        STEP 1 "done"; STEP 2 "done"
        $n++; SP $n

        # Step 4: VPN binaries
        STEP 3 "act"
        AL "=== VPN binaries ==="
        New-Item -ItemType Directory -Force -Path $BIN | Out-Null
        foreach ($b in $BINS) {
            SS "Downloading $($b.N)..." ""
            if (Test-Path $b.D) { AL "  OK $($b.N) (cached)"; $n++; SP $n; continue }
            $tmp = "$env:TEMP\vpnb_$([IO.Path]::GetRandomFileName()).zip"
            try {
                AL "  Downloading $($b.N)..."
                DL $b.U $tmp
                UZE $tmp $b.E $b.D
                Remove-Item $tmp -Force -EA SilentlyContinue
                AL "  OK $($b.N)"
            } catch {
                AL "  FAIL $($b.N): $_" $RED
                Remove-Item $tmp -Force -EA SilentlyContinue
            }
            $n++; SP $n
        }
        STEP 3 "done"

        # Step 5: AmneziaWG
        STEP 4 "act"
        SS "AmneziaWG..." "Installing driver"
        AL "=== AmneziaWG ==="
        if (Test-Path "C:\Program Files\AmneziaWG\wireguard.exe") {
            AL "  OK already installed"; STEP 4 "done"
        } else {
            $msi = "$env:TEMP\awg.msi"
            AL "  Downloading AmneziaWG..."
            DL $AWGMSI $msi
            AL "  Installing MSI (UAC will appear)..."
            $p = Start-Process msiexec -ArgumentList "/i `"$msi`" /quiet /norestart" -Verb RunAs -Wait -PassThru
            Remove-Item $msi -Force -EA SilentlyContinue
            if (Test-Path "C:\Program Files\AmneziaWG\wireguard.exe") {
                AL "  OK AmneziaWG installed"; STEP 4 "done"
            } else {
                AL "  FAIL msiexec exit $($p.ExitCode)" $RED; STEP 4 "err"
            }
        }
        $n++; SP $n

        # Desktop shortcut
        try {
            $lnk = "$env:USERPROFILE\Desktop\VPN Client.lnk"
            $exe = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
            $ws  = New-Object -ComObject WScript.Shell
            $sc  = $ws.CreateShortcut($lnk)
            $sc.TargetPath = $exe; $sc.Arguments = "`"$MAINPY`""
            $sc.WorkingDirectory = $INSTALL; $sc.Save()
            AL "  OK shortcut on Desktop"
        } catch { AL "  shortcut: $_" $RED }

        SP $TOTAL
        AL "=== Done! Click the button to launch ==="
        UI {
            $btn.Enabled = $true
            $lblS.Text = "Setup complete!"
            $lblD.Text = "Click the button to launch VPN Client"
            $lblS.ForeColor = [System.Drawing.Color]::FromArgb(34, 197, 94)
        }

    } catch {
        L "THREAD FATAL: $_"
        L "At: $($_.ScriptStackTrace)"
        AL "ERROR: $_" $RED
        UI {
            $lblS.Text = "Error during setup"
            $lblD.Text = "See log: $LOG"
        }
    }
})

$job.IsBackground = $true
$form.Add_Shown({ 
    L "Form shown, starting thread..."
    $job.Start() 
})

L "Calling Application::Run..."
[System.Windows.Forms.Application]::Run($form)
L "Form closed."
