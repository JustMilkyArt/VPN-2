; MilkyVPN — Inno Setup installer script
; Build command: iscc setup.iss
; Output: Output\MilkyVPN-Setup-1.0.0.exe

#define AppName "MilkyVPN"
#define AppVersion "1.0.0"
#define AppPublisher "MilkyIMS"
#define AppURL "https://admin.milkyims.com"
#define AppExeName "vpn_client.exe"
#define AppGUID "{{A3F2B9C1-7D4E-4F8A-B2E6-9C5D3A1F7E82}"

[Setup]
AppId={#AppGUID}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=no
OutputDir=Output
OutputBaseFilename=MilkyVPN-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
MinVersion=10.0
CloseApplications=yes
CloseApplicationsFilter=*vpn_client.exe*
RestartApplications=no

; UAC + Driver signing
SignTool=
Uninstallable=yes
CreateUninstallRegKey=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked
Name: "startupicon"; Description: "Запускать при входе в Windows"; GroupDescription: "Дополнительно:";

[Files]
; Flutter app
Source: "..\build\windows\x64\runner\Release\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\windows\x64\runner\Release\*.dll"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "..\build\windows\x64\runner\Release\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs

; VPN engine binaries (must be placed in build/engines/ before running iscc)
Source: "engines\xray.exe"; DestDir: "{app}\engines"; Flags: ignoreversion
Source: "engines\naive.exe"; DestDir: "{app}\engines"; Flags: ignoreversion
Source: "engines\awg-quick.exe"; DestDir: "{app}\engines"; Flags: ignoreversion

; WinTUN driver (for AmneziaWG / xray TUN mode)
Source: "engines\wintun.dll"; DestDir: "{app}\engines"; Flags: ignoreversion

; WinTUN driver installer (run post-install)
Source: "engines\wintun-install.inf"; DestDir: "{app}\engines"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Auto-start on login (per user, no UAC)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: "{app}\{#AppExeName}"; \
  Flags: uninsdeletevalue; Tasks: startupicon

[Run]
; Install WinTUN driver silently (needed for AWG and xray TUN)
Filename: "{sys}\PnPutil.exe"; \
  Parameters: "/add-driver ""{app}\engines\wintun-install.inf"" /install"; \
  Flags: runhidden waituntilterminated skipifdoesntexist; \
  Description: "Установка сетевого драйвера WinTUN"

; Launch app after install
Filename: "{app}\{#AppExeName}"; \
  Description: "Запустить {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill VPN process before uninstall
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
Type: filesandordirs; Name: "{app}"

[Code]
// Custom installer pages and logic

procedure InitializeWizard;
begin
  // Set custom wizard page look — nothing extra needed with modern style
end;

function InitializeSetup(): Boolean;
var
  Res: Integer;
begin
  Result := True;
  // Check Windows 10 minimum
  if not IsWindows64BitInstallMode then
  begin
    MsgBox('MilkyVPN требует 64-разрядную версию Windows 10 или новее.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Engines directory: make sure xray/awg/naive are executable
    // (no-op on Windows, but good practice)
  end;
end;
