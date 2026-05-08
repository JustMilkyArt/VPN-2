@echo off
chcp 65001 >nul
echo ============================================
echo  VPN Client — сборка .exe (Windows)
echo ============================================
echo.

:: Проверяем Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не найден. Установите Python 3.11+ с python.org
    pause & exit /b 1
)

:: Устанавливаем зависимости
echo [1/4] Установка зависимостей...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] pip install завершился с ошибкой
    pause & exit /b 1
)

:: Проверяем наличие бинарников
echo [2/4] Проверка бинарников в папке bin\...
set MISSING=0

if not exist "bin\xray.exe" (
    echo   [!] ОТСУТСТВУЕТ: bin\xray.exe
    echo       Скачайте: https://github.com/XTLS/Xray-core/releases
    echo       Нужен файл: Xray-windows-64.zip -> xray.exe
    set MISSING=1
)
if not exist "bin\wintun.dll" (
    echo   [!] ОТСУТСТВУЕТ: bin\wintun.dll
    echo       Скачайте: https://www.wintun.net  -> wintun-0.14.1.zip -> amd64\wintun.dll
    set MISSING=1
)
if not exist "bin\tun2socks.exe" (
    echo   [!] ОТСУТСТВУЕТ: bin\tun2socks.exe
    echo       Скачайте: https://github.com/xjasonlyu/tun2socks/releases
    echo       Нужен файл: tun2socks-windows-amd64.zip -> tun2socks-windows-amd64.exe
    echo       Переименуйте в tun2socks.exe
    set MISSING=1
)
if not exist "bin\naive.exe" (
    echo   [!] ОТСУТСТВУЕТ: bin\naive.exe
    echo       Скачайте: https://github.com/klzgrad/naiveproxy/releases
    echo       Нужен файл: naiveproxy-vXXX-win-x64.zip -> naive.exe
    set MISSING=1
)

if "%MISSING%"=="1" (
    echo.
    echo [ERROR] Положите недостающие файлы в папку bin\ и запустите build.bat снова.
    pause & exit /b 1
)

echo   [OK] Все бинарники найдены.

:: Сборка
echo [3/4] Сборка exe через PyInstaller...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "VPNClient" ^
    --uac-admin ^
    --add-binary "bin\xray.exe;bin" ^
    --add-binary "bin\wintun.dll;bin" ^
    --add-binary "bin\tun2socks.exe;bin" ^
    --add-binary "bin\naive.exe;bin" ^
    --hidden-import PyQt6.QtWidgets ^
    --hidden-import PyQt6.QtCore ^
    --hidden-import PyQt6.QtGui ^
    --hidden-import pyotp ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller завершился с ошибкой
    pause & exit /b 1
)

echo [4/4] Готово!
echo.
echo  Файл: dist\VPNClient.exe
echo.
echo  ВАЖНО: Перед первым запуском установите AmneziaWG:
echo  https://github.com/amnezia-vpn/amneziawg-windows-client/releases
echo  Нужен файл: amneziawg-amd64-X.X.X.msi
echo.
pause
