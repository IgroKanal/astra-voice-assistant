#ifndef PreviewDir
  #error "Pass /DPreviewDir=<verified Astra preview directory>"
#endif
#ifndef AstraVersion
  #error "Pass /DAstraVersion=<product version>"
#endif

[Setup]
AppId={{8C789EB9-22D1-4FB4-8A80-BF29697963A7}
AppName=Astra Voice Assistant
SetupIconFile={#PreviewDir}\assets\branding\astra.ico
AppVersion={#AstraVersion}
AppPublisher=Astra Voice Assistant
DefaultDirName={localappdata}\Programs\Astra Voice Assistant
DefaultGroupName=Astra Voice Assistant
PrivilegesRequired=lowest
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputBaseFilename=Astra-Setup-{#AstraVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=no
UninstallDisplayName=Astra Voice Assistant
UninstallDisplayIcon={app}\Astra.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoCompany=Astra Voice Assistant
VersionInfoDescription=Astra Voice Assistant installer
VersionInfoProductName=Astra Voice Assistant
VersionInfoProductVersion={#AstraBinaryVersion}
VersionInfoTextVersion={#AstraVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked

[Files]
Source: "{#PreviewDir}\*"; DestDir: "{app}"; Excludes: "logs\*,*.log,*.tmp"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Astra Voice Assistant"; Filename: "{app}\Astra.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Astra Voice Assistant"; Filename: "{app}\Astra.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Astra.exe"; Description: "Запустить Astra Voice Assistant"; WorkingDir: "{app}"; Flags: postinstall skipifsilent nowait

; User data lives in %LOCALAPPDATA%\AstraVoiceAssistant and is deliberately
; absent from [UninstallDelete], so uninstall never removes settings, memory,
; reminders, TTS cache, or logs.
