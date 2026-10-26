#define AppVersion GetEnv("M3_READER_VERSION")
#if AppVersion == ""
  #error M3_READER_VERSION must be set by package_installpacks.py
#endif

[Setup]
AppId=M3Reader
AppName=M3 Reader
AppVersion={#AppVersion}
AppPublisher=M3 Reader
DefaultDirName={code:LegacyInstallDir}
UsePreviousAppDir=yes
DisableDirPage=no
DirExistsWarning=no
PrivilegesRequired=lowest
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes
ChangesEnvironment=yes
UninstallDisplayIcon={app}\bin\windows\m3-reader-gui.exe
OutputDir=..\installpacks\windows
OutputBaseFilename=m3-reader-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："

[Files]
Source: "..\bin\windows\m3-reader.exe"; DestDir: "{app}\bin\windows"; Flags: ignoreversion
Source: "..\bin\windows\m3-reader-gui.exe"; DestDir: "{app}\bin\windows"; Flags: ignoreversion

[Dirs]
Name: "{app}\workspace"; Flags: uninsneveruninstall

[InstallDelete]
Type: files; Name: "{app}\bin\windows\m3-reader-gui-old.exe"
Type: files; Name: "{app}\bin\windows\m3-reader-gui-2.6.0.exe"
Type: files; Name: "{app}\bin\windows\m3-reader-gui.exe.previous-*"
Type: files; Name: "{app}\bin\windows\m3-reader.exe.previous-*"

[Icons]
Name: "{autoprograms}\M3 Reader"; Filename: "{app}\bin\windows\m3-reader-gui.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\M3 Reader"; Filename: "{app}\bin\windows\m3-reader-gui.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\M3 Reader"; ValueType: string; ValueName: "InstallLocation"; ValueData: "{app}"; Flags: uninsdeletekeyifempty

[Code]
var
  ResourcesPage: TInputDirWizardPage;
  ResourcesCustomized: Boolean;

procedure InitializeWizard;
var
  Previous: String;
begin
  ResourcesPage := CreateInputDirPage(wpSelectDir, '资料目录',
    '选择 resources 目录',
    '可以沿用已有资料目录。安装和更新程序不会删除其中的文件。',
    False, SetupMessage(msgNewFolderName));
  ResourcesPage.Add('resources 目录');
  if RegQueryStringValue(HKCU, 'Software\M3 Reader', 'ResourcesLocation', Previous) then begin
    ResourcesPage.Values[0] := Previous;
    ResourcesCustomized := True;
  end else begin
    ResourcesPage.Values[0] := AddBackslash(WizardDirValue) + 'resources';
    ResourcesCustomized := False;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = ResourcesPage.ID) and not ResourcesCustomized then
    ResourcesPage.Values[0] := AddBackslash(WizardDirValue) + 'resources';
end;

function ValidResources(const Directory: String): Boolean;
var
  Found: TFindRec;
  Item: String;
begin
  Result := True;
  if not DirExists(Directory) then Exit;
  if FindFirst(AddBackslash(Directory) + '*', Found) then begin
    try
      repeat
        Item := Lowercase(Found.Name);
        if (Item <> '.') and (Item <> '..') and
           (Item <> 'collected') and (Item <> 'ocr') and
           (Item <> 'local') and (Item <> 'updates') and
           (Item <> 'readme.md') then begin
          Result := False;
          Exit;
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

function HasEntries(const Directory: String): Boolean;
var
  Found: TFindRec;
begin
  Result := False;
  if not DirExists(Directory) then Exit;
  if FindFirst(AddBackslash(Directory) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin
          Result := True;
          Exit;
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

function HasResources(const Root: String): Boolean;
begin
  Result := HasEntries(AddBackslash(Root) + 'collected\prts_text') or
    HasEntries(AddBackslash(Root) + 'collected\terra') or
    HasEntries(AddBackslash(Root) + 'ocr\terra_text') or
    HasEntries(AddBackslash(Root) + 'local') or
    HasEntries(AddBackslash(Root) + 'updates\new');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID <> ResourcesPage.ID then Exit;
  if not ValidResources(ResourcesPage.Values[0]) then begin
    MsgBox('该目录包含不属于 resources 的项目。请选择一个空目录或已有 resources 目录。', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if HasResources(ResourcesPage.Values[0]) and not WizardSilent then
    MsgBox('检测到已有资源文件或目录。安装程序将保留并继续使用它们。', mbInformation, MB_OK);
  ResourcesCustomized := True;
end;

function PathContains(const Current, Target: String): Boolean;
var
  Remaining, Entry: String;
  Separator: Integer;
begin
  Result := False;
  Remaining := Current;
  while Remaining <> '' do begin
    Separator := Pos(';', Remaining);
    if Separator = 0 then begin
      Entry := Remaining;
      Remaining := '';
    end else begin
      Entry := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if Lowercase(Trim(Entry)) = Lowercase(Target) then begin
      Result := True;
      Exit;
    end;
  end;
end;

procedure RegisterCommandPath;
var
  Current, Target: String;
begin
  Target := AddBackslash(WizardDirValue) + 'bin\windows';
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Current) then Current := '';
  if PathContains(Current, Target) then Exit;
  if Current <> '' then Current := Current + ';';
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Current + Target);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Root := ResourcesPage.Values[0];
  ForceDirectories(AddBackslash(Root) + 'collected\prts_text');
  ForceDirectories(AddBackslash(Root) + 'collected\terra');
  ForceDirectories(AddBackslash(Root) + 'ocr\terra_text');
  ForceDirectories(AddBackslash(Root) + 'local');
  ForceDirectories(AddBackslash(Root) + 'updates\new');
  RegWriteStringValue(HKCU, 'Software\M3 Reader', 'ResourcesLocation', Root);
  RegisterCommandPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Current, Remaining, Entry, Updated, Target: String;
  Separator: Integer;
begin
  if CurUninstallStep <> usUninstall then Exit;
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Current) then Exit;
  Target := AddBackslash(ExpandConstant('{app}')) + 'bin\windows';
  Remaining := Current;
  Updated := '';
  while Remaining <> '' do begin
    Separator := Pos(';', Remaining);
    if Separator = 0 then begin
      Entry := Remaining;
      Remaining := '';
    end else begin
      Entry := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if (Entry <> '') and (Lowercase(Trim(Entry)) <> Lowercase(Target)) then begin
      if Updated <> '' then Updated := Updated + ';';
      Updated := Updated + Entry;
    end;
  end;
  if Updated <> Current then
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Updated);
end;

function RootFromShortcut(const ShortcutPath: String): String;
var
  Shell, Shortcut: Variant;
  Target: String;
begin
  Result := '';
  if not FileExists(ShortcutPath) then Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(ShortcutPath);
    Target := Shortcut.TargetPath;
    if FileExists(Target) and
       (Lowercase(ExtractFileName(Target)) = 'm3-reader-gui.exe') and
       (Lowercase(ExtractFileName(ExtractFileDir(Target))) = 'windows') and
       (Lowercase(ExtractFileName(ExtractFileDir(ExtractFileDir(Target)))) = 'bin') then
      Result := ExtractFileDir(ExtractFileDir(ExtractFileDir(Target)));
  except
    Result := '';
  end;
end;

function LegacyInstallDir(Param: String): String;
var
  Saved, Found: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\M3 Reader');
  if RegQueryStringValue(HKCU, 'Software\M3 Reader', 'InstallLocation', Saved) and
     FileExists(AddBackslash(Saved) + 'bin\windows\m3-reader-gui.exe') then begin
    Result := Saved;
    Exit;
  end;
  Found := RootFromShortcut(ExpandConstant('{userdesktop}\M3 Reader.lnk'));
  if Found = '' then
    Found := RootFromShortcut(ExpandConstant('{userprograms}\M3 Reader.lnk'));
  if Found <> '' then Result := Found;
end;
