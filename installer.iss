#define MyAppName "RenPy Tools"
#define MyAppVersion "0.2.6"
#define MyAppPublisher "RenPy Tools"

[Setup]
; Keep this AppId unchanged so every future installer is treated as an update.
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

; Upgrade behaviour: reuse the installed folder and replace old program files.
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
CreateUninstallRegKey=yes

[Files]
; ignoreversion intentionally overwrites the previous EXEs during an in-place update.
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
