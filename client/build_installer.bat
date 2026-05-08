@echo off
chcp 65001 > nul
title VPN Client — Build Installer

echo.
echo ============================================
echo   VPN Client — Сборка установщика
echo ============================================
echo.

:: Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python 3.10+ с https://python.org
    pause
    exit /b 1
)

:: Установка зависимостей для сборки
echo [1/3] Установка зависимостей...
pip install PyQt6 requests pyotp pyinstaller --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости
    pause
    exit /b 1
)

echo [2/3] Сборка installer.exe...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "VPNClient_Setup" ^
    --icon assets\icon.ico ^
    --add-data "core;core" ^
    --add-data "ui;ui" ^
    --add-data "assets;assets" ^
    --add-data "config.py;." ^
    --add-data "main.py;." ^
    --hidden-import PyQt6.QtCore ^
    --hidden-import PyQt6.QtWidgets ^
    --hidden-import PyQt6.QtGui ^
    --hidden-import pyotp ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    --clean ^
    installer.py

if errorlevel 1 (
    echo [ОШИБКА] Сборка не удалась
    pause
    exit /b 1
)

echo [3/3] Готово!
echo.
echo Установщик: dist\VPNClient_Setup.exe
echo.
echo Что делает установщик при запуске:
echo  - Скачивает xray.exe, wintun.dll, tun2socks.exe, naive.exe
echo  - Устанавливает AmneziaWG (драйвер для AWG подключений)
echo  - Устанавливает Python зависимости
echo  - Запускает VPN Client
echo.
pause
