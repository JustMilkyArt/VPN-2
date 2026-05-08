# VPN Client Installer v9 - single thread, DoEvents only

$LOG = "$env:USERPROFILE\vpnclient_setup.log"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function L($m) { Add-Content $LOG "[$(Get-Date -f 'HH:mm:ss')] $m" -EA SilentlyContinue }
L "=== v9 started ==="

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
    @{N="Xray";      U="https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip"; E="xray.exe"; D="$BIN\xray.exe"},
    @{N="WinTUN";    U="https://www.wintun.net/builds/wintun-0.14.1.zip"; E="wintun/bin/amd64/wintun.dll"; D="$BIN\wintun.dll"},
    @{N="tun2socks"; U="https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip"; E="tun2socks-windows-amd64.exe"; D="$BIN\tun2socks.exe"},
    @{N="Naive";     U="https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip"; E="naive.exe"; D="$BIN\naive.exe"}
)
$TOTAL = $SOURCES.Count + $BINS.Count + 5

L "Loading WinForms..."
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
[void][System.Reflection.Assembly]::LoadWithPartialName("System.Drawing")
L "WinForms loaded"

[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = "VPN Client - Setup"
$form.Width = 480; $form.Height = 520
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(18,20,28)
$form.ForeColor = [System.Drawing.Color]::White
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$lbTitle = New-Object System.Windows.Forms.Label
$lbTitle.Text = "VPN Client"; $lbTitle.Width = 440; $lbTitle.Height = 34
$lbTitle.Left = 20; $lbTitle.Top = 18; $lbTitle.TextAlign = "MiddleCenter"
$lbTitle.Font = New-Object System.Drawing.Font("Segoe UI",17,[System.Drawing.FontStyle]::Bold)
$lbTitle.ForeColor = [System.Drawing.Color]::White
$lbTitle.BackColor = [System.Drawing.Color]::Transparent
$form.Controls.Add($lbTitle)

$lbSub = New-Object System.Windows.Forms.Label
$lbSub.Text = "VLESS Reality  |  AmneziaWG  |  NaiveProxy"
$lbSub.Width = 440; $lbSub.Height = 18; $lbSub.Left = 20; $lbSub.Top = 56
$lbSub.TextAlign = "MiddleCenter"
$lbSub.Font = New-Object System.Drawing.Font("Segoe UI",8)
$lbSub.ForeColor = [System.Drawing.Color]::FromArgb(120,130,150)
$lbSub.BackColor = [System.Drawing.Color]::Transparent
$form.Controls.Add($lbSub)

$card = New-Object System.Windows.Forms.Panel
$card.Width = 440; $card.Height = 72; $card.Left = 20; $card.Top = 84
$card.BackColor = [System.Drawing.Color]::FromArgb(26,30,42)
$form.Controls.Add($card)

$lbS = New-Object System.Windows.Forms.Label
$lbS.Text = "Preparing..."; $lbS.Width = 400; $lbS.Height = 22
$lbS.Left = 16; $lbS.Top = 8
$lbS.Font = New-Object System.Drawing.Font("Segoe UI",10,[System.Drawing.FontStyle]::Bold)
$lbS.ForeColor = [System.Drawing.Color]::White
$lbS.BackColor = [System.Drawing.Color]::Transparent
$card.Controls.Add($lbS)

$lbD = New-Object System.Windows.Forms.Label
$lbD.Text = "Starting..."; $lbD.Width = 400; $lbD.Height = 18
$lbD.Left = 16; $lbD.Top = 34
$lbD.Font = New-Object System.Drawing.Font("Segoe UI",8)
$lbD.ForeColor = [System.Drawing.Color]::FromArgb(120,130,150)
$lbD.BackColor = [System.Drawing.Color]::Transparent
$card.Controls.Add($lbD)

$pb = New-Object System.Windows.Forms.ProgressBar
$pb.Width = 400; $pb.Height = 10; $pb.Left = 16; $pb.Top = 56
$pb.Maximum = 100; $pb.Value = 0; $pb.Style = "Continuous"
$card.Controls.Add($pb)

$stepNames = @("Code","Python","Deps","VPN","AWG")
$dots = @()
for ($i = 0; $i -lt 5; $i++) {
    $d = New-Object System.Windows.Forms.Label
    $d.Text = "o"; $d.Width = 88; $d.Height = 22
    $d.Left = 20+$i*88; $d.Top = 170; $d.TextAlign = "MiddleCenter"
    $d.Font = New-Object System.Drawing.Font("Segoe UI",11)
    $d.BackColor = [System.Drawing.Color]::Transparent
    $d.ForeColor = [System.Drawing.Color]::FromArgb(80,90,110)
    $form.Controls.Add($d); $dots += $d
    $n2 = New-Object System.Windows.Forms.Label
    $n2.Text = $stepNames[$i]; $n2.Width = 88; $n2.Height = 16
    $n2.Left = 20+$i*88; $n2.Top = 192; $n2.TextAlign = "MiddleCenter"
    $n2.Font = New-Object System.Drawing.Font("Segoe UI",7)
    $n2.BackColor = [System.Drawing.Color]::Transparent
    $n2.ForeColor = [System.Drawing.Color]::FromArgb(80,90,110)
    $form.Controls.Add($n2)
}

$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.Width = 440; $rtb.Height = 200; $rtb.Left = 20; $rtb.Top = 218
$rtb.BackColor = [System.Drawing.Color]::FromArgb(12,14,20)
$rtb.ForeColor = [System.Drawing.Color]::FromArgb(50,200,80)
$rtb.Font = New-Object System.Drawing.Font("Consolas",8)
$rtb.ReadOnly = $true; $rtb.BorderStyle = "None"; $rtb.ScrollBars = "Vertical"
$form.Controls.Add($rtb)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = "Open VPN Client"; $btn.Width = 440; $btn.Height = 42
$btn.Left = 20; $btn.Top = 432
$btn.Font = New-Object System.Drawing.Font("Segoe UI",10,[System.Drawing.FontStyle]::Bold)
$btn.BackColor = [System.Drawing.Color]::FromArgb(99,90,240)
$btn.ForeColor = [System.Drawing.Color]::White
$btn.FlatStyle = "Flat"; $btn.FlatAppearance.BorderSize = 0
$btn.Enabled = $false; $btn.Cursor = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btn)

L "Form built"

$RED   = [System.Drawing.Color]::FromArgb(239,68,68)
$GREEN = [System.Drawing.Color]::FromArgb(50,200,80)
$AMBER = [System.Drawing.Color]::FromArgb(245,158,11)

# All UI calls happen on the SAME thread — no Invoke, no threads
function Tick { [System.Windows.Forms.Application]::DoEvents() }

function Log($msg, $col) {
    L $msg
    if (-not $col) { $col = $GREEN }
    $rtb.SelectionStart = $rtb.TextLength
    $rtb.SelectionLength = 0
    $rtb.SelectionColor = $col
    $rtb.AppendText("$msg`n")
    $rtb.ScrollToCaret()
    Tick
}

function Status($title, $detail) {
    $lbS.Text = $title
    if ($detail -ne $null) { $lbD.Text = $detail }
    Tick
}

function Prog($n) {
    $pb.Value = [Math]::Min([int]($n / $TOTAL * 100), 100)
    Tick
}

function Dot($i, $s) {
    $sym = if ($s -eq "done") {"*"} elseif ($s -eq "err") {"!"} else {">"}
    $col = if ($s -eq "done") {[System.Drawing.Color]::FromArgb(34,197,94)} `
           elseif ($s -eq "err") {$RED} else {$AMBER}
    $dots[$i].Text = $sym; $dots[$i].ForeColor = $col
    Tick
}

function DL($url, $dest) {
    $dir = Split-Path $dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $wc = New-Object Net.WebClient
    $wc.Headers.Add("User-Agent","VPNClient/9")
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

$btn.Add_Click({
    $exe = if (Test-Path $PYWEXE) {$PYWEXE} else {$PYEXE}
    Start-Process $exe -ArgumentList "`"$MAINPY`"" -WorkingDirectory $INSTALL
    $form.Close()
})

# Install runs on form Shown event — same UI thread, DoEvents keeps form alive
$form.Add_Shown({
    L "Form shown — starting install"
    Tick

    try {
        $n = 0

        # Step 1: Source code
        Dot 0 "act"; Status "Downloading source code..." "GitHub"; Log "=== Source code ==="
        New-Item -ItemType Directory -Force -Path $INSTALL | Out-Null
        foreach ($f in $SOURCES) {
            $dst = "$INSTALL\$($f -replace '/','\')"
            $dir = Split-Path $dst
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            try   { DL "$GHRAW/$f" $dst; Log "  OK $f" }
            catch { Log "  FAIL $f : $_" $RED }
            $n++; Prog $n
        }
        Dot 0 "done"

        # Step 2: Python
        Dot 1 "act"; Status "Python 3.12..." "Downloading portable"; Log "=== Python 3.12 ==="
        if (Test-Path $PYEXE) {
            Log "  OK already installed"
        } else {
            $pz = "$env:TEMP\py312.zip"
            Log "  Downloading Python 3.12..."
            DL $PYZIP $pz
            Log "  Extracting..."
            New-Item -ItemType Directory -Force -Path $PYDIR | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($pz, $PYDIR)
            Remove-Item $pz -Force -EA SilentlyContinue
            $pth = Get-ChildItem $PYDIR -Filter "*._pth" | Select-Object -First 1
            if ($pth) {
                (Get-Content $pth.FullName) -replace '#import site','import site' | Set-Content $pth.FullName
            }
            Log "  OK Python ready"
        }
        $n++; Prog $n

        if (-not (Test-Path $PIPEXE)) {
            Log "  Installing pip..."
            $gp = "$env:TEMP\get-pip.py"
            DL $GETPIP $gp
            & $PYEXE $gp "--quiet" 2>$null
            Remove-Item $gp -Force -EA SilentlyContinue
            Log "  OK pip"
        }
        $n++; Prog $n

        # Step 3: Dependencies
        Dot 2 "act"; Status "Installing packages..." "PyQt6 requests pyotp"; Log "=== Dependencies ==="
        foreach ($dep in @("PyQt6","requests","pyotp")) {
            Log "  pip install $dep..."
            try   { & $PIPEXE install $dep "--quiet" "--no-warn-script-location" 2>$null; Log "  OK $dep" }
            catch { Log "  FAIL $dep : $_" $RED }
        }
        Dot 1 "done"; Dot 2 "done"; $n++; Prog $n

        # Step 4: VPN binaries
        Dot 3 "act"; Log "=== VPN binaries ==="
        New-Item -ItemType Directory -Force -Path $BIN | Out-Null
        foreach ($b in $BINS) {
            Status "Downloading $($b.N)..." ""
            if (Test-Path $b.D) { Log "  OK $($b.N) cached"; $n++; Prog $n; continue }
            $tmp = "$env:TEMP\vpnb_$([IO.Path]::GetRandomFileName()).zip"
            try {
                Log "  Downloading $($b.N)..."
                DL $b.U $tmp
                UZE $tmp $b.E $b.D
                Remove-Item $tmp -Force -EA SilentlyContinue
                Log "  OK $($b.N)"
            } catch {
                Log "  FAIL $($b.N): $_" $RED
                Remove-Item $tmp -Force -EA SilentlyContinue
            }
            $n++; Prog $n
        }
        Dot 3 "done"

        # Step 5: AmneziaWG
        Dot 4 "act"; Status "AmneziaWG..." "Installing driver"; Log "=== AmneziaWG ==="
        if (Test-Path "C:\Program Files\AmneziaWG\wireguard.exe") {
            Log "  OK already installed"; Dot 4 "done"
        } else {
            $msi = "$env:TEMP\awg.msi"
            Log "  Downloading AmneziaWG..."
            DL $AWGMSI $msi
            Log "  Installing (UAC will appear)..."
            $p = Start-Process msiexec -ArgumentList "/i `"$msi`" /quiet /norestart" -Verb RunAs -Wait -PassThru
            Remove-Item $msi -Force -EA SilentlyContinue
            if (Test-Path "C:\Program Files\AmneziaWG\wireguard.exe") {
                Log "  OK AmneziaWG installed"; Dot 4 "done"
            } else {
                Log "  FAIL msiexec exit $($p.ExitCode)" $RED; Dot 4 "err"
            }
        }
        $n++; Prog $n

        # Shortcut
        try {
            $exe = if (Test-Path $PYWEXE) {$PYWEXE} else {$PYEXE}
            $ws = New-Object -ComObject WScript.Shell
            $sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\VPN Client.lnk")
            $sc.TargetPath = $exe; $sc.Arguments = "`"$MAINPY`""
            $sc.WorkingDirectory = $INSTALL; $sc.Save()
            Log "  OK shortcut on Desktop"
        } catch { Log "  shortcut: $_" $RED }

        Prog $TOTAL
        Log "=== Setup complete! ==="
        $lbS.Text = "Setup complete!"
        $lbD.Text = "Click button to launch"
        $lbS.ForeColor = [System.Drawing.Color]::FromArgb(34,197,94)
        $btn.Enabled = $true
        L "Done — button enabled"
        Tick

    } catch {
        L "FATAL: $_"
        L "Stack: $($_.ScriptStackTrace)"
        Log "FATAL ERROR: $_" $RED
        $lbS.Text = "Error during setup"
        $lbD.Text = "See log: $LOG"
        $lbS.ForeColor = $RED
        Tick
    }
})

L "Calling Application::Run..."
[System.Windows.Forms.Application]::Run($form)
L "Form closed."
