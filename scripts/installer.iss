; ============================================================
; installer.iss — instalador por usuario (Inno Setup 6)
; Uso: ISCC.exe scripts\installer.iss
; Requiere dist\port-forwarder\ (build de PyInstaller previa)
; ============================================================
#define MyAppName "Port Forwarding Manager"
#define MyAppVersion "0.1.0"
#define MyAppExeName "port-forwarder.exe"

[Setup]
AppId={{8F2A3C1E-5D4B-4A7E-9C10-2F3B4A5C6D7E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Port Forwarding Manager
DefaultDirName={localappdata}\Programs\PortForwarder
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PortForwarder-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\port-forwarder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (CLI)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--help"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "doctor"; Description: "Diagnostico del entorno"; Flags: nowait postinstall skipifsilent
