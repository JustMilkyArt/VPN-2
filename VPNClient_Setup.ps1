# VPN Client — Automatic Setup & Launcher
# Запускать от имени Администратора (Run as Administrator)
# PowerShell 5+ (встроен в Windows 10/11)

param([switch]$Silent)

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════
#  Настройки
# ═══════════════════════════════════════════════════════════════════

$InstallDir  = "$env:LOCALAPPDATA\VPNClient"
$BinDir      = "$InstallDir\bin"
$PythonDir   = "$InstallDir\python"
$PythonExe   = "$PythonDir\python.exe"
$PipExe      = "$PythonDir\Scripts\pip.exe"
$MainPy      = "$InstallDir\main.py"
$LogFile     = "$env:USERPROFILE\vpnclient_setup.log"

$PythonUrl   = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip"
$GetPipUrl   = "https://bootstrap.pypa.io/get-pip.py"

$AwgMsiUrl   = "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/2.0.0/amneziawg-amd64-2.0.0.msi"

$Downloads = @(
    @{
        Label   = "Xray-core (VLESS Reality)"
        Url     = "https://github.com/XTLS/Xray-core/releases/download/v25.4.30/Xray-windows-64.zip"
        ZipName = "xray.exe"
        Dest    = "$BinDir\xray.exe"
    },
    @{
        Label   = "WinTUN driver"
        Url     = "https://www.wintun.net/builds/wintun-0.14.1.zip"
        ZipName = "wintun/bin/amd64/wintun.dll"
        Dest    = "$BinDir\wintun.dll"
    },
    @{
        Label   = "tun2socks"
        Url     = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.5.2/tun2socks-windows-amd64.zip"
        ZipName = "tun2socks-windows-amd64.exe"
        Dest    = "$BinDir\tun2socks.exe"
    },
    @{
        Label   = "NaiveProxy"
        Url     = "https://github.com/klzgrad/naiveproxy/releases/download/v148.0.7778.96-2/naiveproxy-v148.0.7778.96-2-win-x64.zip"
        ZipName = "naive.exe"
        Dest    = "$BinDir\naive.exe"
    }
)

# ═══════════════════════════════════════════════════════════════════
#  Логирование
# ═══════════════════════════════════════════════════════════════════

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

function LogOK($msg)  { Log "✓ $msg" }
function LogErr($msg) { Log "✗ $msg" }
function LogInfo($msg){ Log "  $msg" }

# ═══════════════════════════════════════════════════════════════════
#  UI — прогресс в консоли
# ═══════════════════════════════════════════════════════════════════

function ShowProgress($step, $total, $label) {
    $pct  = [int](($step / $total) * 100)
    $bar  = "#" * [int]($pct / 5)
    $empty = "-" * (20 - $bar.Length)
    Write-Host "`r  [$bar$empty] $pct%  $label" -NoNewline
    if ($pct -eq 100) { Write-Host "" }
}

# ═══════════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════════════

function Download($url, $dest) {
    $client = New-Object System.Net.WebClient
    $client.Headers.Add("User-Agent", "VPNClient/1.0")
    $client.DownloadFile($url, $dest)
    $client.Dispose()
}

function ExtractFromZip($zipPath, $memberSuffix, $dest) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entry = $zip.Entries | Where-Object {
            $_.FullName -eq $memberSuffix -or
            $_.FullName.EndsWith("/" + ($memberSuffix -split "/" | Select-Object -Last 1)) -or
            $_.Name -eq ($memberSuffix -split "/" | Select-Object -Last 1)
        } | Select-Object -First 1

        if (-not $entry) {
            $names = ($zip.Entries | Select-Object -First 10 -ExpandProperty FullName) -join ", "
            throw "Файл '$memberSuffix' не найден в архиве. Есть: $names"
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
    } finally {
        $zip.Dispose()
    }
}

function IsAwgInstalled {
    $paths = @(
        "C:\Program Files\AmneziaWG\wireguard.exe",
        "C:\Program Files (x86)\AmneziaWG\wireguard.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function TestInternetConnection {
    try {
        $null = Invoke-WebRequest -Uri "https://github.com" -UseBasicParsing -TimeoutSec 10
        return $true
    } catch {
        return $false
    }
}

# ═══════════════════════════════════════════════════════════════════
#  Проверка прав администратора
# ═══════════════════════════════════════════════════════════════════

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  ОШИБКА: Запустите скрипт от имени Администратора!" -ForegroundColor Red
    Write-Host "  Щёлкните правой кнопкой → 'Запустить от имени администратора'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Нажмите Enter для выхода"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
#  Заголовок
# ═══════════════════════════════════════════════════════════════════

Clear-Host
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║       VPN Client — Установка             ║" -ForegroundColor Cyan
Write-Host "  ║  VLESS Reality · AmneziaWG · NaiveProxy  ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Log "Начало установки. InstallDir: $InstallDir"

# ═══════════════════════════════════════════════════════════════════
#  Интернет
# ═══════════════════════════════════════════════════════════════════

Write-Host "  Проверка интернет-соединения..." -ForegroundColor Gray
if (-not (TestInternetConnection)) {
    LogErr "Нет интернет-соединения. Установка прервана."
    Read-Host "  Нажмите Enter для выхода"
    exit 1
}
LogOK "Интернет доступен"

# ═══════════════════════════════════════════════════════════════════
#  Папки
# ═══════════════════════════════════════════════════════════════════

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir     | Out-Null
New-Item -ItemType Directory -Force -Path $PythonDir  | Out-Null
LogOK "Папки созданы: $InstallDir"

# ═══════════════════════════════════════════════════════════════════
#  Python (embedded)
# ═══════════════════════════════════════════════════════════════════

if (Test-Path $PythonExe) {
    LogOK "Python уже установлен: $PythonExe"
} else {
    Write-Host ""
    Write-Host "  [1/6] Скачивание Python 3.12 (portable)..." -ForegroundColor Yellow
    $pyZip = "$env:TEMP\python-embed.zip"
    try {
        Download $PythonUrl $pyZip
        LogInfo "Распаковка Python..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($pyZip, $PythonDir)
        Remove-Item $pyZip -ErrorAction SilentlyContinue

        # Разрешаем импорт site-packages (нужно для pip-пакетов)
        $pthFile = Get-ChildItem $PythonDir -Filter "*._pth" | Select-Object -First 1
        if ($pthFile) {
            $content = Get-Content $pthFile.FullName
            $newContent = $content -replace "#import site", "import site"
            Set-Content $pthFile.FullName $newContent
        }

        LogOK "Python 3.12 установлен"
    } catch {
        LogErr "Ошибка Python: $_"
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════════════
#  pip
# ═══════════════════════════════════════════════════════════════════

if (-not (Test-Path $PipExe)) {
    Write-Host "  [2/6] Установка pip..." -ForegroundColor Yellow
    $getPip = "$env:TEMP\get-pip.py"
    try {
        Download $GetPipUrl $getPip
        & $PythonExe $getPip --quiet
        Remove-Item $getPip -ErrorAction SilentlyContinue
        LogOK "pip установлен"
    } catch {
        LogErr "Ошибка pip: $_"
        exit 1
    }
} else {
    LogOK "pip уже есть"
}

# ═══════════════════════════════════════════════════════════════════
#  Python зависимости
# ═══════════════════════════════════════════════════════════════════

Write-Host "  [3/6] Установка Python-зависимостей..." -ForegroundColor Yellow
$deps = @("PyQt6", "requests", "pyotp")
foreach ($dep in $deps) {
    try {
        LogInfo "pip install $dep"
        & $PipExe install $dep --quiet --no-warn-script-location
    } catch {
        LogErr "pip install $dep failed: $_"
    }
}
LogOK "Зависимости установлены"

# ═══════════════════════════════════════════════════════════════════
#  Исходный код VPN клиента
# ═══════════════════════════════════════════════════════════════════

Write-Host "  [4/6] Получение исходного кода VPN клиента..." -ForegroundColor Yellow

# Если файлы уже рядом (пользователь распаковал ZIP), копируем их
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceFiles = @("main.py", "config.py", "core", "ui", "assets")
$hasSource = Test-Path (Join-Path $scriptDir "main.py")

if ($hasSource) {
    LogInfo "Копирование файлов из $scriptDir..."
    foreach ($item in $sourceFiles) {
        $src = Join-Path $scriptDir $item
        $dst = Join-Path $InstallDir $item
        if (Test-Path $src) {
            if ((Get-Item $src).PSIsContainer) {
                if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
                Copy-Item $src $dst -Recurse -Force
            } else {
                Copy-Item $src $dst -Force
            }
        }
    }
    LogOK "Файлы скопированы в $InstallDir"
} else {
    LogErr "Исходные файлы не найдены рядом со скриптом!"
    LogInfo "Убедитесь, что VPNClient_Setup.bat находится в одной папке с main.py, core\, ui\"
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
#  Бинарники (xray, wintun, tun2socks, naive)
# ═══════════════════════════════════════════════════════════════════

Write-Host "  [5/6] Скачивание VPN бинарников..." -ForegroundColor Yellow
$i = 0
foreach ($item in $Downloads) {
    $i++
    $dest = $item.Dest
    if (Test-Path $dest) {
        LogOK "$($item.Label) — уже есть"
        continue
    }
    LogInfo "Скачивание $($item.Label)..."
    $tmpZip = "$env:TEMP\vpnclient_dl_$i.zip"
    try {
        Download $item.Url $tmpZip
        ExtractFromZip $tmpZip $item.ZipName $dest
        Remove-Item $tmpZip -ErrorAction SilentlyContinue
        LogOK "$($item.Label) готов"
    } catch {
        LogErr "Ошибка $($item.Label): $_"
        # Не прерываем — другие протоколы продолжат работать
    }
}

# ═══════════════════════════════════════════════════════════════════
#  AmneziaWG
# ═══════════════════════════════════════════════════════════════════

Write-Host "  [6/6] AmneziaWG..." -ForegroundColor Yellow
if (IsAwgInstalled) {
    LogOK "AmneziaWG уже установлен"
} else {
    LogInfo "Скачивание AmneziaWG MSI..."
    $msiPath = "$env:TEMP\amneziawg.msi"
    try {
        Download $AwgMsiUrl $msiPath
        LogInfo "Установка AmneziaWG (тихая)..."
        Start-Process msiexec -ArgumentList "/i `"$msiPath`" /quiet /norestart" -Wait
        Remove-Item $msiPath -ErrorAction SilentlyContinue
        if (IsAwgInstalled) {
            LogOK "AmneziaWG установлен"
        } else {
            LogErr "AmneziaWG установить не удалось — AWG подключения будут недоступны"
        }
    } catch {
        LogErr "Ошибка AmneziaWG: $_"
        LogInfo "→ Установите вручную: https://github.com/amnezia-vpn/amneziawg-windows-client/releases"
    }
}

# ═══════════════════════════════════════════════════════════════════
#  Создание ярлыка на рабочем столе
# ═══════════════════════════════════════════════════════════════════

try {
    $WshShell    = New-Object -ComObject WScript.Shell
    $shortcut    = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\VPN Client.lnk")
    $shortcut.TargetPath       = $PythonExe
    $shortcut.Arguments        = "`"$MainPy`""
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description      = "VPN Client — VLESS Reality, AmneziaWG, NaiveProxy"
    $shortcut.Save()
    LogOK "Ярлык создан на рабочем столе"
} catch {
    LogErr "Ярлык не создан: $_"
}

# ═══════════════════════════════════════════════════════════════════
#  Запуск VPN клиента
# ═══════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "  ══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅  Установка завершена! Запуск VPN Client..." -ForegroundColor Green
Write-Host "  ══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Log "Запуск: $PythonExe $MainPy"

Start-Process $PythonExe -ArgumentList "`"$MainPy`"" -WorkingDirectory $InstallDir

Write-Host "  VPN Client запущен." -ForegroundColor Cyan
Write-Host "  Ярлык на рабочем столе: 'VPN Client'" -ForegroundColor Cyan
Write-Host ""
Start-Sleep -Seconds 3
