@echo off
:: VPN Client — One-click Setup
:: Двойной клик → UAC → установка → запуск VPN
:: Требования: Windows 10/11, интернет

title VPN Client Setup

:: ── Запрос прав администратора (UAC) ────────────────────────────────────────
net session >nul 2>&1
if %errorLevel% == 0 goto :ADMIN_OK

echo.
echo  Запрос прав администратора...
echo  (Нажмите "Да" в окне UAC)
echo.

:: Перезапускаем себя через PowerShell с UAC
powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
exit /b

:ADMIN_OK
:: ── Мы администратор, запускаем PowerShell скрипт ───────────────────────────

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%VPNClient_Setup.ps1"

if not exist "%PS1%" (
    echo.
    echo  ОШИБКА: VPNClient_Setup.ps1 не найден!
    echo  Убедитесь что .bat и .ps1 файлы находятся в одной папке.
    echo.
    pause
    exit /b 1
)

:: Снимаем ограничение на выполнение скриптов и запускаем
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"

if %errorLevel% neq 0 (
    echo.
    echo  Установка завершилась с ошибкой. См. лог: %USERPROFILE%\vpnclient_setup.log
    pause
)
