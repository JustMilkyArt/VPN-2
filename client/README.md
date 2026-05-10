# MilkyVPN — Windows Client

Flutter-based Windows VPN client for MilkyIMS infrastructure.

## Architecture

```
Flutter App (UI + state)
      ↓
VpnProvider (Provider pattern)
      ↓
VpnEngine (subprocess manager)
      ↓
┌─────────────┬──────────────┬─────────────┐
│  xray.exe   │ awg-quick.exe│  naive.exe  │
│ VLESS+Reality│  AmneziaWG  │  NaiveProxy │
│   Trojan    │              │             │
└─────────────┴──────────────┴─────────────┘
      ↓
Windows SOCKS5 system proxy / WinTUN adapter
      ↓
VPN tunnel to server
```

## How connections are fetched

On startup the app calls:
```
GET https://admin.milkyims.com/api/v1/client/connections
X-API-Key: <CLIENT_API_KEY>
```
Returns active VPN connections with full client configs.
Results are cached locally for 24 h (works offline).

## Building

### Prerequisites
- Flutter 3.x with Windows desktop support (`flutter config --enable-windows-desktop`)
- Inno Setup 6 (https://jrsoftware.org/isinfo.php)
- Engine binaries (see below)

### Engine binaries

Place these in `installer/engines/` before running the build script:

| File | Download |
|------|----------|
| `xray.exe` | https://github.com/XTLS/Xray-core/releases — `Xray-windows-64.zip` |
| `naive.exe` | https://github.com/klzgrad/naiveproxy/releases — `naiveproxy-plugin-windows-x86_64.zip` |
| `awg-quick.exe` | https://github.com/amnezia-vpn/amneziawg-windows/releases |
| `wintun.dll` | https://www.wintun.net — extract `wintun/bin/amd64/wintun.dll` |

### Build steps

```bat
cd client
installer\build_and_pack.bat
```

Output: `installer\Output\MilkyVPN-Setup-1.0.0.exe`

### Manual build

```bat
flutter build windows --release
iscc installer\setup.iss
```

## Backend API key setup

1. Generate a key on the server:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Add to server `.env`:
   ```
   CLIENT_API_KEY=<generated-key>
   ```
3. Update `lib/utils/constants.dart` → `clientApiKey` with the same value before building.

## Project structure

```
lib/
├── main.dart               # App entry point, window + tray setup
├── models/
│   └── connection.dart     # VpnConnection, Protocol, VpnStatus
├── services/
│   ├── api_service.dart    # Fetch connections from backend + local cache
│   ├── vpn_engine.dart     # Launch/kill xray/awg/naive subprocesses
│   ├── vpn_provider.dart   # ChangeNotifier state management
│   └── tray_service.dart   # System tray icon + context menu
├── screens/
│   └── home_screen.dart    # Main window UI
├── widgets/
│   ├── connection_card.dart # Single connection list item
│   └── connect_button.dart  # Animated connect/disconnect button
└── utils/
    └── constants.dart      # API URL, key, timeouts, file names
installer/
├── setup.iss               # Inno Setup script
├── build_and_pack.bat      # One-click build script
└── engines/                # Place engine binaries here (not committed)
assets/
├── engines/                # Extracted at runtime to app support dir
└── icons/                  # App + tray icons
```

## VPN modes

| Protocol | Engine | Routing |
|----------|--------|---------|
| VLESS + Reality | xray.exe | SOCKS5 system proxy (127.0.0.1:10808) |
| Trojan | xray.exe | SOCKS5 system proxy |
| NaiveProxy | naive.exe | SOCKS5 system proxy |
| AmneziaWG | awg-quick.exe | Full TUN (WinTUN driver, all traffic) |

**AmneziaWG** routes all traffic through the VPN (true tunnel).  
**VLESS/Trojan/Naive** use SOCKS5 — most apps respect system proxy automatically.
