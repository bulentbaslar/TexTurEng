; Inno Setup script for the laptop (CPU / cloud) build of TexTurEng.
; Installs per user, so no administrator rights are needed.
#define AppName "TexTurEng"
#define AppVersion "0.6.0"

[Setup]
AppId={{6F70E6DE-6C28-4F61-9FCB-6F718D252C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Bulent Baslar
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Textureng-Setup
SetupIconFile=..\textureng.ico
UninstallDisplayIcon={app}\Textureng.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Textureng\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Textureng.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Textureng.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Textureng.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM Textureng.exe /F"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
// On uninstall, remove the "Start with Windows" entry (the app creates it from
// Settings), but only when it starts this installed copy. A copy of the app run from
// source uses the same entry name and must keep its entry.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}', Command) then
      if Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Command)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;
