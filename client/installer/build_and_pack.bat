@echo off
REM MilkyVPN — build script
REM Run from: client\ directory
REM Requirements: Flutter SDK, Inno Setup 6, ISCC.exe in PATH

setlocal enabledelayedexpansion

echo ============================================================
echo  MilkyVPN Build Script
echo ============================================================

REM 1. Flutter build
echo [1/4] Building Flutter Windows release...
flutter build windows --release
if errorlevel 1 (
    echo ERROR: Flutter build failed
    exit /b 1
)
echo OK

REM 2. Copy engine binaries into installer/engines/
echo [2/4] Copying VPN engine binaries...
set ENGINES_DIR=installer\engines
if not exist %ENGINES_DIR% mkdir %ENGINES_DIR%

REM These must be downloaded manually (see README)
set MISSING=0
for %%F in (xray.exe naive.exe awg-quick.exe wintun.dll) do (
    if not exist %ENGINES_DIR%\%%F (
        echo   MISSING: %ENGINES_DIR%\%%F
        set MISSING=1
    )
)
if !MISSING! == 1 (
    echo.
    echo ERROR: Place engine binaries in installer\engines\ before building.
    echo See client\README.md for download links.
    exit /b 1
)
echo OK

REM 3. Copy app icon
echo [3/4] Checking icons...
if not exist installer\app.ico (
    echo   WARNING: installer\app.ico not found. Using default icon.
)

REM 4. Run Inno Setup
echo [4/4] Building installer with Inno Setup...
where iscc >nul 2>&1
if errorlevel 1 (
    REM Try default Inno Setup install path
    set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
) else (
    set ISCC=iscc
)

!ISCC! installer\setup.iss
if errorlevel 1 (
    echo ERROR: Inno Setup failed
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  Installer: installer\Output\MilkyVPN-Setup-1.0.0.exe
echo ============================================================
