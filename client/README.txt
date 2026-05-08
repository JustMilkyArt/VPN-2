============================================
 VPN Client — инструкция по установке
============================================

ЧТО ЭТО
--------
Десктопный VPN клиент для Windows.
Поддерживает все протоколы из вашей админ-панели:
  • AmneziaWG (прямые и каскадные)
  • VLESS + Reality (прямые и каскадные)
  • NaiveProxy (прямые и каскадные)

Все подключения — полноценный VPN (весь трафик через тоннель).


ШАГ 1 — УСТАНОВИТЕ AmneziaWG (один раз)
-----------------------------------------
Скачайте и установите (требуются права администратора):
https://github.com/amnezia-vpn/amneziawg-windows-client/releases

Файл: amneziawg-amd64-X.X.X.msi

Это нужно для протокола AmneziaWG.
Для VLESS и NaiveProxy AmneziaWG не нужен.


ШАГ 2 — СКАЧАЙТЕ БИНАРНИКИ в папку bin\
-----------------------------------------
Папка bin\ должна содержать 4 файла:

1. xray.exe
   Откуда: https://github.com/XTLS/Xray-core/releases
   Архив:  Xray-windows-64.zip
   Нужен:  xray.exe

2. wintun.dll
   Откуда: https://www.wintun.net
   Архив:  wintun-0.14.1.zip
   Нужен:  wintun\bin\amd64\wintun.dll  → скопировать как bin\wintun.dll

3. tun2socks.exe
   Откуда: https://github.com/xjasonlyu/tun2socks/releases
   Архив:  tun2socks-windows-amd64.zip
   Нужен:  tun2socks-windows-amd64.exe  → переименовать в tun2socks.exe

4. naive.exe
   Откуда: https://github.com/klzgrad/naiveproxy/releases
   Архив:  naiveproxy-vXXX-win-x64.zip
   Нужен:  naive.exe


ШАГ 3 — СОБЕРИТЕ .EXE (на Windows)
-------------------------------------
Откройте командную строку в папке проекта и запустите:

   build.bat

Или вручную:
   pip install -r requirements.txt
   pyinstaller --onefile --windowed --name VPNClient --uac-admin ^
     --add-binary "bin\xray.exe;bin" ^
     --add-binary "bin\wintun.dll;bin" ^
     --add-binary "bin\tun2socks.exe;bin" ^
     --add-binary "bin\naive.exe;bin" ^
     main.py

Результат: dist\VPNClient.exe


ШАГ 4 — ЗАПУСТИТЕ
-------------------
Запустите dist\VPNClient.exe от имени администратора
(правая кнопка → "Запустить от имени администратора")

Или: приложение само запросит права при старте (UAC).


КАК РАБОТАЕТ
-------------
• Список подключений загружается автоматически из API
• Выберите подключение → нажмите "Подключиться"
• AmneziaWG: использует wireguard.exe из установленного AmneziaWG
• VLESS Reality: xray.exe + wintun.dll (нативный TUN)
• NaiveProxy: naive.exe + tun2socks.exe (TUN через SOCKS5)
• Весь трафик идёт через VPN после подключения
• "Отключиться" — полное отключение и восстановление маршрутов

ЛОГИ
-----
При проблемах смотрите лог-файл:
  %USERPROFILE%\vpnclient.log
  (обычно C:\Users\ВашеИмя\vpnclient.log)


СТРУКТУРА ПРОЕКТА
------------------
vpnclient/
  main.py              — точка входа
  config.py            — настройки API
  core/
    api_client.py      — получение подключений из API
    vpn_manager.py     — оркестратор протоколов
    protocols/
      awg_manager.py   — AmneziaWG
      vless_manager.py — VLESS + Reality
      naive_manager.py — NaiveProxy
  ui/
    main_window.py     — главное окно (PyQt6)
  bin/                 — бинарники (xray, wintun, tun2socks, naive)
  build.bat            — скрипт сборки
  requirements.txt     — зависимости Python
============================================
