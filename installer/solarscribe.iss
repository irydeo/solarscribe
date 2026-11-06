; SolarScribe - Inno Setup script (Windows installer)
;
; Built by the "CI" GitHub Actions workflow:
;   ISCC.exe /DAppVersion=<version> /DAppSuffix=<suffix> installer\solarscribe.iss
; Input:  ..\dist\solarscribe\  (PyInstaller onedir output)
; Output: ..\dist\SolarScribeSetup-<version><suffix>.exe
;
; Per-user install under %LOCALAPPDATA%\Programs: no admin rights needed.
; The ASCOM Platform is a prerequisite for the mount and is NOT bundled; the
; installer detects it and explains what to install. The app degrades to the
; simulator when it is absent (ADR-014, ADR-017).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifndef AppSuffix
  #define AppSuffix ""
#endif

[Setup]
; Stable identifier of the app (upgrades and uninstall hang from it; never change it)
AppId={{f1610f28-fe64-43cf-acdc-a43fa06c83cd}
AppName=SolarScribe
AppVersion={#AppVersion}
AppPublisher=Francisco José Calvo Fernández (Irydeo Observatory, MPC Z41)
AppPublisherURL=https://www.irydeo.com
AppSupportURL=https://github.com/irydeo/solarscribe/issues
SetupIconFile=..\installer\icons\solarscribe.ico
DefaultDirName={localappdata}\Programs\SolarScribe
DefaultGroupName=SolarScribe
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SolarScribeSetup-{#AppVersion}{#AppSuffix}
LicenseFile=..\LICENSE
; The prerequisite note is shown before the copy: the ASCOM Platform and its
; .NET runtime are separate installations, and saying so here is cheaper than
; a support report after the observer wonders why the mount is missing.
InfoBeforeFile=..\installer\PREREQUISITES.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=SolarScribe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The SDK binaries, the .ui/.qm files and the per-SDK notices are inside the
; PyInstaller tree already; the installer copies the tree as one unit so a
; missing DLL and a partial upgrade cannot happen.
Source: "..\dist\solarscribe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The current native loader asks ctypes for the bare DLL name, and Windows
; searches the executable's folder. Copy the approved SDK DLLs next to the
; exe as well as keeping the sdk/<vendor> tree for a future sdk_dir() lookup.
; PyInstaller 6 puts binaries under _internal\; older layouts put them at the
; bundle root, so both are tried and skipifsourcedoesntexist keeps a bundle
; without SDKs valid.
Source: "..\dist\solarscribe\sdk\*\*.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\solarscribe\_internal\sdk\*\*.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; The per-SDK attribution is inside the PyInstaller tree under _internal;
; put a copy at the top level so the observer can find it from the Start menu
; folder without knowing PyInstaller's layout.
Source: "..\dist\solarscribe\_internal\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\installer\PREREQUISITES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SolarScribe"; Filename: "{app}\solarscribe.exe"; Parameters: "gui"
Name: "{autodesktop}\SolarScribe"; Filename: "{app}\solarscribe.exe"; Parameters: "gui"; Tasks: desktopicon

[Run]
Filename: "{app}\solarscribe.exe"; Parameters: "gui"; Description: "{cm:LaunchProgram,SolarScribe}"; Flags: nowait postinstall skipifsilent

[Code]
// Inno Setup, with the same AppId, does NOT uninstall the previous version: it
// installs over it and APPENDS to the same uninstall log. Files the new build
// no longer ships, and a PyInstaller onedir tree changes a lot between
// versions, so we run the previous uninstaller ourselves, silently, before
// copying. Settings and sessions live in the platformdirs folder
// (%LOCALAPPDATA%\SolarScribe), never in the app folder, so they survive.

function PreviousUninstallString(): String;
var
  Key, Cmd: String;
begin
  Result := '';
  { The uninstall registry key is the AppId plus "_is1". Our AppId is written
    with a doubled opening brace (an escaped literal), so ExpandConstant turns
    it back into a single one. The install is per-user, so HKCU is the normal
    place; HKLM is checked as a fallback. }
  Key := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  if not RegQueryStringValue(HKCU, Key, 'UninstallString', Cmd) then
    RegQueryStringValue(HKLM, Key, 'UninstallString', Cmd);
  Result := Cmd;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Cmd: String;
  ResultCode: Integer;
begin
  Result := '';
  Cmd := PreviousUninstallString();
  if Cmd = '' then
    Exit;                          { nothing installed: this is a first install }
  { The uninstaller cannot delete solarscribe.exe while the app is running, and
    a locked file would be left behind (and the copy below would fail). }
  Exec('taskkill.exe', '/F /IM solarscribe.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Cmd := RemoveQuotes(Cmd);        { the path may carry spaces }
  if (not Exec(Cmd, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
               ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    Result := 'The previous version of SolarScribe could not be uninstalled. ' +
              'Uninstall it from Settings > Apps, then run this installer again.';
end;

function AscomInstalled(): Boolean;
var
  Value: String;
begin
  { ASCOM Platform 6 and 7 register under SOFTWARE\ASCOM\Platform. The app is
    64-bit, but the platform key may be in the 64-bit view, the WOW6432Node
    view or HKCU depending on how it was installed, so all three are tried. }
  Result :=
    RegQueryStringValue(HKLM64, 'SOFTWARE\ASCOM\Platform', 'Version', Value) or
    RegQueryStringValue(HKLM, 'SOFTWARE\ASCOM\Platform', 'Version', Value) or
    RegQueryStringValue(HKCU, 'SOFTWARE\ASCOM\Platform', 'Version', Value);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { A silent or unattended install must never wait on a dialog. The same
      warning is in PREREQUISITES.txt, which the wizard shows before the copy. }
    if (not AscomInstalled()) and (not WizardSilent()) then
      MsgBox('The ASCOM Platform was not found. The camera and the SHG engine ' +
             'work without it, but the telescope needs ASCOM Platform 7 (and ' +
             'the .NET runtime it requires). Install it from ascom-standards.org ' +
             'and reopen SolarScribe.',
             mbInformation, MB_OK);
  end;
end;
