# VPN Client Installer — WPF GUI (встроен в Windows 10/11)
# Запускается через: powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File installer.ps1
# Требует прав администратора (UAC запрашивает .bat файл до запуска этого скрипта)

Set-StrictMode -Off
$ErrorActionPreference = 'SilentlyContinue'
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# ─── Пути ────────────────────────────────────────────────────────────────────

$INSTALL  = "$env:LOCALAPPDATA\VPNClient"
$BIN      = "$INSTALL\bin"
$PYDIR    = "$INSTALL\python"
$PYEXE    = "$PYDIR\python.exe"
$PYWEXE   = "$PYDIR\pythonw.exe"
$PIPEXE   = "$PYDIR\Scripts\pip.exe"
$MAINPY   = "$INSTALL\main.py"
$LOGFILE  = "$env:USERPROFILE\vpnclient_setup.log"
$GHRAW    = "https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main"

$PYZIP    = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
$GETPIP   = "https://bootstrap.pypa.io/get-pip.py"
$AWGMSI   = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"

$SOURCES  = @(
    "main.py","config.py","requirements.txt",
    "core/__init__.py","core/api_client.py","core/vpn_manager.py",
    "core/protocols/__init__.py","core/protocols/awg_manager.py",
    "core/protocols/vless_manager.py","core/protocols/naive_manager.py",
    "ui/__init__.py","ui/main_window.py"
)

$BINS = @(
    @{ L="Xray-core (VLESS Reality)"; U="https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip";                                                                  E="xray.exe";                    D="$BIN\xray.exe"     },
    @{ L="WinTUN driver";             U="https://www.wintun.net/builds/wintun-0.14.1.zip";                                                                                                    E="wintun/bin/amd64/wintun.dll"; D="$BIN\wintun.dll"   },
    @{ L="tun2socks";                 U="https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip";                                                       E="tun2socks-windows-amd64.exe"; D="$BIN\tun2socks.exe"},
    @{ L="NaiveProxy";                U="https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip";                                 E="naive.exe";                   D="$BIN\naive.exe"    }
)

$TOTAL = $SOURCES.Count + $BINS.Count + 5   # +python +pip +deps +awg +shortcut

# ─── Helpers ─────────────────────────────────────────────────────────────────

function Log($msg) {
    $line = "[$(Get-Date -f 'HH:mm:ss')] $msg"
    Add-Content $LOGFILE $line -EA SilentlyContinue
    return $line
}

function DL($url, $dest) {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent","VPNClient-Installer/3.0")
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    $wc.DownloadFile($url, $dest)
    $wc.Dispose()
}

function Unzip-Entry($zip, $entry, $dest) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [System.IO.Compression.ZipFile]::OpenRead($zip)
    $fname = ($entry -split '/')[-1]
    $e = $z.Entries | Where-Object { $_.FullName -eq $entry -or $_.Name -eq $fname } | Select-Object -First 1
    if (-not $e) { $z.Dispose(); throw "Not found: $entry" }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
    $z.Dispose()
}

function AwgInstalled {
    return (Test-Path "C:\Program Files\AmneziaWG\wireguard.exe") -or
           (Test-Path "C:\Program Files (x86)\AmneziaWG\wireguard.exe")
}

# ─── WPF XAML ────────────────────────────────────────────────────────────────

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms

[xml]$XAML = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="VPN Client — Установка"
        Width="520" Height="580"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Background="#0F1117"
        Foreground="#E2E8F0"
        FontFamily="Segoe UI">

  <Window.Resources>
    <Style x:Key="SubText" TargetType="TextBlock">
      <Setter Property="Foreground" Value="#64748B"/>
      <Setter Property="FontSize"   Value="11"/>
    </Style>
    <Style x:Key="StepDot" TargetType="TextBlock">
      <Setter Property="FontSize"   Value="18"/>
      <Setter Property="Foreground" Value="#64748B"/>
      <Setter Property="HorizontalAlignment" Value="Center"/>
    </Style>
  </Window.Resources>

  <Grid Margin="0">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Шапка -->
    <StackPanel Grid.Row="0" Background="#0F1117" Margin="0,28,0,16">
      <TextBlock Text="🔒" FontSize="40" HorizontalAlignment="Center"
                 FontFamily="Segoe UI Emoji" Foreground="#6C63FF"/>
      <TextBlock Text="VPN Client" FontSize="22" FontWeight="Bold"
                 HorizontalAlignment="Center" Foreground="White" Margin="0,6,0,0"/>
      <TextBlock Text="VLESS Reality  ·  AmneziaWG  ·  NaiveProxy"
                 FontSize="10" HorizontalAlignment="Center" Foreground="#64748B" Margin="0,3,0,0"/>
    </StackPanel>

    <!-- Статус-карточка -->
    <Border Grid.Row="1" Margin="24,0,24,16" Background="#161B27"
            BorderBrush="#252B3B" BorderThickness="1" CornerRadius="10">
      <Grid Margin="20,14,20,14">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="8"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="4"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Точка статуса -->
        <TextBlock x:Name="DotStatus" Grid.Column="0" Grid.Row="0" Grid.RowSpan="3"
                   Text="⬤" FontSize="20" Foreground="#F59E0B"
                   VerticalAlignment="Center" Margin="0,0,14,0"/>

        <!-- Заголовок -->
        <TextBlock x:Name="LblStatus" Grid.Column="1" Grid.Row="0"
                   Text="Подготовка…" FontSize="13" FontWeight="SemiBold"
                   Foreground="White"/>

        <!-- Детали -->
        <TextBlock x:Name="LblDetail" Grid.Column="1" Grid.Row="2"
                   Text="Инициализация" FontSize="10" Foreground="#64748B"
                   TextWrapping="Wrap"/>

        <!-- Прогресс-бар -->
        <Grid Grid.Column="0" Grid.Row="4" Grid.ColumnSpan="2" Margin="0,10,0,0">
          <ProgressBar x:Name="PBar" Height="7" Minimum="0" Maximum="100" Value="0"
                       Background="#1E2435" BorderThickness="0">
            <ProgressBar.Foreground>
              <LinearGradientBrush StartPoint="0,0" EndPoint="1,0">
                <GradientStop Color="#6C63FF" Offset="0"/>
                <GradientStop Color="#8B5CF6" Offset="1"/>
              </LinearGradientBrush>
            </ProgressBar.Foreground>
          </ProgressBar>
          <TextBlock x:Name="LblPct" Text="0%" HorizontalAlignment="Right"
                     Foreground="#64748B" FontSize="9" Margin="0,10,0,0"
                     VerticalAlignment="Top"/>
        </Grid>
      </Grid>
    </Border>

    <!-- Шаги -->
    <UniformGrid Grid.Row="2" Rows="1" Margin="24,0,24,14">
      <StackPanel x:Name="Step1" HorizontalAlignment="Center">
        <TextBlock x:Name="Dot1" Text="○" Style="{StaticResource StepDot}"/>
        <TextBlock Text="Код"    Style="{StaticResource SubText}" HorizontalAlignment="Center" FontSize="9"/>
      </StackPanel>
      <StackPanel x:Name="Step2" HorizontalAlignment="Center">
        <TextBlock x:Name="Dot2" Text="○" Style="{StaticResource StepDot}"/>
        <TextBlock Text="Python" Style="{StaticResource SubText}" HorizontalAlignment="Center" FontSize="9"/>
      </StackPanel>
      <StackPanel x:Name="Step3" HorizontalAlignment="Center">
        <TextBlock x:Name="Dot3" Text="○" Style="{StaticResource StepDot}"/>
        <TextBlock Text="Пакеты" Style="{StaticResource SubText}" HorizontalAlignment="Center" FontSize="9"/>
      </StackPanel>
      <StackPanel x:Name="Step4" HorizontalAlignment="Center">
        <TextBlock x:Name="Dot4" Text="○" Style="{StaticResource StepDot}"/>
        <TextBlock Text="VPN"    Style="{StaticResource SubText}" HorizontalAlignment="Center" FontSize="9"/>
      </StackPanel>
      <StackPanel x:Name="Step5" HorizontalAlignment="Center">
        <TextBlock x:Name="Dot5" Text="○" Style="{StaticResource StepDot}"/>
        <TextBlock Text="AWG"    Style="{StaticResource SubText}" HorizontalAlignment="Center" FontSize="9"/>
      </StackPanel>
    </UniformGrid>

    <!-- Лог -->
    <Border Grid.Row="3" Margin="24,0,24,14" Background="#0D1018"
            BorderBrush="#252B3B" BorderThickness="1" CornerRadius="8">
      <ScrollViewer x:Name="LogScroll" VerticalScrollBarVisibility="Auto" Padding="2">
        <TextBlock x:Name="LogBox" Padding="10,8" FontFamily="Consolas"
                   FontSize="10" Foreground="#2D6B2D"
                   TextWrapping="Wrap"/>
      </ScrollViewer>
    </Border>

    <!-- Кнопка -->
    <Button x:Name="BtnLaunch" Grid.Row="4"
            Content="🚀  Открыть VPN Client"
            Margin="24,0,24,22" Height="46"
            FontSize="13" FontWeight="SemiBold" FontFamily="Segoe UI"
            Foreground="White" Background="#6C63FF"
            BorderThickness="0" Cursor="Hand"
            IsEnabled="False">
      <Button.Template>
        <ControlTemplate TargetType="Button">
          <Border x:Name="Bd" Background="{TemplateBinding Background}"
                  CornerRadius="10">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="#7D75FF"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter TargetName="Bd" Property="Background" Value="#1E2435"/>
              <Setter Property="Foreground" Value="#3A3A5A"/>
            </Trigger>
            <Trigger Property="IsPressed" Value="True">
              <Setter TargetName="Bd" Property="Background" Value="#5A52EF"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Button.Template>
    </Button>
  </Grid>
</Window>
'@

# ─── Создаём окно ────────────────────────────────────────────────────────────

$reader = New-Object System.Xml.XmlNodeReader $XAML
$Window = [Windows.Markup.XamlReader]::Load($reader)

# Получаем элементы
$DotStatus = $Window.FindName("DotStatus")
$LblStatus = $Window.FindName("LblStatus")
$LblDetail = $Window.FindName("LblDetail")
$PBar      = $Window.FindName("PBar")
$LblPct    = $Window.FindName("LblPct")
$LogBox    = $Window.FindName("LogBox")
$LogScroll = $Window.FindName("LogScroll")
$BtnLaunch = $Window.FindName("BtnLaunch")
$Dots      = @(
    $Window.FindName("Dot1"),
    $Window.FindName("Dot2"),
    $Window.FindName("Dot3"),
    $Window.FindName("Dot4"),
    $Window.FindName("Dot5")
)

# ─── UI helpers (обновление из фонового потока через Dispatcher) ──────────────

function UI([scriptblock]$sb) {
    $Window.Dispatcher.Invoke($sb)
}

$script:done = 0

function SetStatus($title, $detail="", $dotColor="#F59E0B") {
    UI { $LblStatus.Text  = $title; $LblDetail.Text = $detail; $DotStatus.Foreground = $dotColor }
}

function AddLog($msg, $color="#2D6B2D") {
    $line = Log $msg
    UI {
        $run = New-Object System.Windows.Documents.Run
        $run.Text       = $line + "`n"
        $run.Foreground = [System.Windows.Media.BrushConverter]::new().ConvertFromString($color)
        if ($LogBox.Inlines -eq $null) {
            # TextBlock не поддерживает Inlines напрямую — просто добавляем текст
            $LogBox.Text += $line + "`n"
        } else {
            $LogBox.Inlines.Add($run)
        }
        $LogBox.Text += $line + "`n"
        $LogScroll.ScrollToEnd()
    }
}

function Step($idx, $state) {
    # state: active | done | error
    $sym   = @{active="◉"; done="●"; error="●"}[$state]
    $color = @{active="#F59E0B"; done="#22C55E"; error="#EF4444"}[$state]
    UI { $Dots[$idx].Text = $sym; $Dots[$idx].Foreground = $color }
}

function Progress($n) {
    $script:done = $n
    $pct = [int]($n / $TOTAL * 100)
    UI { $PBar.Value = $pct; $LblPct.Text = "$pct%" }
}

function EnableLaunch() {
    UI {
        $BtnLaunch.IsEnabled = $true
        $DotStatus.Foreground = "#22C55E"
    }
}

# ─── Кнопка запуска ──────────────────────────────────────────────────────────

$BtnLaunch.Add_Click({
    $exe = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
    Start-Process $exe -ArgumentList "`"$MAINPY`"" -WorkingDirectory $INSTALL
    $Window.Close()
})

# ─── Установка (фоновый поток) ───────────────────────────────────────────────

$installJob = [System.Threading.Thread]::new([System.Threading.ThreadStart]{

    $n = 0

    # ── 1. Исходный код ────────────────────────────────────────────────────
    Step 0 "active"
    SetStatus "Скачивание VPN Client…" "Загрузка файлов с GitHub"
    AddLog "=== Исходный код ==="
    foreach ($f in $SOURCES) {
        $dst = "$INSTALL\$($f -replace '/','\\')"
        $url = "$GHRAW/$f"
        try { DL $url $dst; AddLog "  ✓ $f" }
        catch { AddLog "  ✗ $f : $_" "#EF4444" }
        $n++; Progress $n
    }
    Step 0 "done"

    # ── 2. Python ──────────────────────────────────────────────────────────
    Step 1 "active"
    SetStatus "Python 3.12…" "Портативная версия для VPN Client"
    AddLog "=== Python 3.12 ==="
    if (Test-Path $PYEXE) {
        AddLog "  ✓ Python уже установлен"
    } else {
        try {
            AddLog "  ⬇ Скачивание Python…"
            $pz = "$env:TEMP\py312-embed.zip"
            DL $PYZIP $pz
            AddLog "  Распаковка…"
            New-Item -ItemType Directory -Force -Path $PYDIR | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::ExtractToDirectory($pz, $PYDIR)
            Remove-Item $pz -Force -EA SilentlyContinue
            # Включаем site-packages
            $pth = Get-ChildItem $PYDIR -Filter "*._pth" | Select-Object -First 1
            if ($pth) {
                (Get-Content $pth.FullName) -replace '#import site','import site' |
                    Set-Content $pth.FullName
            }
            AddLog "  ✓ Python 3.12 готов"
        } catch {
            AddLog "  ✗ Python: $_" "#EF4444"
            Step 1 "error"
        }
    }
    $n++; Progress $n

    # pip
    if (-not (Test-Path $PIPEXE)) {
        AddLog "  Установка pip…"
        try {
            $gp = "$env:TEMP\get-pip.py"
            DL $GETPIP $gp
            & $PYEXE $gp "--quiet" 2>$null
            Remove-Item $gp -Force -EA SilentlyContinue
            AddLog "  ✓ pip готов"
        } catch { AddLog "  ✗ pip: $_" "#EF4444" }
    }
    $n++; Progress $n

    # ── 3. Зависимости ────────────────────────────────────────────────────
    Step 2 "active"
    SetStatus "Python-зависимости…" "PyQt6, requests, pyotp"
    AddLog "=== Зависимости ==="
    foreach ($dep in @("PyQt6","requests","pyotp")) {
        AddLog "  pip install $dep…"
        try { & $PIPEXE install $dep "--quiet" "--no-warn-script-location" 2>$null; AddLog "  ✓ $dep" }
        catch { AddLog "  ✗ $dep : $_" "#EF4444" }
    }
    Step 1 "done"; Step 2 "done"
    $n++; Progress $n

    # ── 4. VPN бинарники ──────────────────────────────────────────────────
    Step 3 "active"
    AddLog "=== VPN модули ==="
    New-Item -ItemType Directory -Force -Path $BIN | Out-Null
    foreach ($b in $BINS) {
        SetStatus "Скачивание: $($b.L)…" "VPN компоненты"
        if (Test-Path $b.D) {
            AddLog "  ✓ $($b.L) (уже есть)"
            $n++; Progress $n; continue
        }
        $tmp = "$env:TEMP\vpnbin_$([System.IO.Path]::GetRandomFileName()).zip"
        try {
            AddLog "  ⬇ $($b.L)…"
            DL $b.U $tmp
            Unzip-Entry $tmp $b.E $b.D
            Remove-Item $tmp -Force -EA SilentlyContinue
            AddLog "  ✓ $($b.L)"
        } catch {
            AddLog "  ✗ $($b.L): $_" "#EF4444"
            Remove-Item $tmp -Force -EA SilentlyContinue
        }
        $n++; Progress $n
    }
    Step 3 "done"

    # ── 5. AmneziaWG ──────────────────────────────────────────────────────
    Step 4 "active"
    SetStatus "AmneziaWG…" "Установка WireGuard драйвера"
    AddLog "=== AmneziaWG ==="
    if (AwgInstalled) {
        AddLog "  ✓ AmneziaWG уже установлен"
        Step 4 "done"
    } else {
        $msi = "$env:TEMP\awg-setup.msi"
        try {
            AddLog "  ⬇ Скачивание AmneziaWG…"
            DL $AWGMSI $msi
            AddLog "  Установка…"
            $p = Start-Process msiexec -ArgumentList "/i `"$msi`" /quiet /norestart" -Wait -PassThru
            Remove-Item $msi -Force -EA SilentlyContinue
            if (AwgInstalled) { AddLog "  ✓ AmneziaWG установлен"; Step 4 "done" }
            else               { AddLog "  ✗ msiexec завершился: $($p.ExitCode)" "#EF4444"; Step 4 "error" }
        } catch {
            AddLog "  ✗ AmneziaWG: $_" "#EF4444"
            Step 4 "error"
        }
    }
    $n++; Progress $n

    # ── Ярлык ─────────────────────────────────────────────────────────────
    SetStatus "Создание ярлыка…" ""
    try {
        $desk = "$env:USERPROFILE\Desktop"
        $link = "$desk\VPN Client.lnk"
        $exe  = if (Test-Path $PYWEXE) { $PYWEXE } else { $PYEXE }
        $ws   = New-Object -ComObject WScript.Shell
        $sc   = $ws.CreateShortcut($link)
        $sc.TargetPath       = $exe
        $sc.Arguments        = "`"$MAINPY`""
        $sc.WorkingDirectory = $INSTALL
        $sc.Description      = "VPN Client"
        $sc.Save()
        AddLog "  ✓ Ярлык 'VPN Client' на рабочем столе"
    } catch { AddLog "  ✗ Ярлык: $_" "#EF4444" }

    Progress $TOTAL

    # ── Готово ────────────────────────────────────────────────────────────
    SetStatus "Установка завершена!" "Нажмите кнопку для запуска VPN Client" "#22C55E"
    AddLog "=== Готово! Нажмите кнопку ниже ==="
    EnableLaunch
})

$installJob.IsBackground = $true
$installJob.Start()

# ─── Показываем окно (блокирует до закрытия) ─────────────────────────────────
$Window.ShowDialog() | Out-Null
