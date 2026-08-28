; Sprint 18 Phase A: unsigned, per-user internal-test installer only.
; The build module supplies MyAppVersion, MyStageDir, and MyOutputDir.

#ifndef MyAppVersion
  #error MyAppVersion must be supplied from the canonical Python package version.
#endif
#ifndef MyStageDir
  #error MyStageDir must point to a verified PyInstaller onedir staging folder.
#endif
#ifndef MyOutputDir
  #error MyOutputDir must be an isolated candidate directory.
#endif
#ifndef MyDisableShellIntegration
  #define MyDisableShellIntegration "0"
#endif

#ifndef MyAppNumericVersion
  #define MyAppNumericVersion MyAppVersion
#endif

#define MyAppName "StockTool"
#define MyAppId "{{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}"
#define MyPublisher "StockTool Internal Test"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppNumericVersion}
VersionInfoProductVersion={#MyAppNumericVersion}
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductTextVersion={#MyAppVersion}
AppPublisher={#MyPublisher}
DefaultDirName={localappdata}\Programs\StockTool
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=StockTool-Setup-{#MyAppVersion}-internal-test
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#MyAppName} (Internal Test)

[Files]
Source: "{#MyStageDir}\StockTool.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyStageDir}\Payload\*"; DestDir: "{app}\versions\{#MyAppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    #ifdef MyFailAfterPayloadCopy
      RaiseException('Synthetic interrupted update after payload copy and before authority switch.');
    #endif
    if not Exec(ExpandConstant('{app}\StockTool.exe'), '--activate-version {#MyAppVersion}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Stable entry activation could not be started.')
    else if ResultCode <> 0 then
      RaiseException('Stable entry activation failed with exit code ' + IntToStr(ResultCode) + '.');
  end;
end;

#if MyDisableShellIntegration == "0"
  [Icons]
  Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\StockTool.exe"; WorkingDir: "{app}"

  [Run]
  Filename: "{app}\StockTool.exe"; WorkingDir: "{app}"; Description: "Launch StockTool"; Flags: nowait postinstall skipifsilent
#endif

[UninstallDelete]
Type: filesandordirs; Name: "{app}\versions"
Type: files; Name: "{app}\current-version.json"
Type: files; Name: "{app}\current-version.json.tmp"
