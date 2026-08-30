#define MyAppName "RenPy Tools"
#define MyAppVersion "0.3.0"
#define MyAppPublisher "RenPy Tools"

[Setup]
AppId={{7D9B6AC1-0A46-4C4A-A6FA-7B0DD5371F85}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\RenPyTools
DefaultGroupName=RenPy Tools
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=RenPyTools_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\RenPyAIPatcher.exe

[Files]
Source: "dist\RenPyExtractor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\RenPyAIPatcher.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RenPy Extractor"; Filename: "{app}\RenPyExtractor.exe"
Name: "{group}\RenPy AI Patcher"; Filename: "{app}\RenPyAIPatcher.exe"
Name: "{autodesktop}\RenPy Extractor"; Filename: "{app}\RenPyExtractor.exe"; Tasks: desktopicon
Name: "{autodesktop}\RenPy AI Patcher"; Filename: "{app}\RenPyAIPatcher.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 작업:"; Flags: unchecked

[Run]
Filename: "{app}\RenPyAIPatcher.exe"; Description: "RenPy AI Patcher 실행"; Flags: nowait postinstall skipifsilent
