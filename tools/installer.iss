; 서무비서 AI 설치 프로그램 (Inno Setup 6) — 설치하고 바로 실행한다.
;   iscc /DAppVer=1.0.0 tools\installer.iss   →  dist\SeomuAI-Setup.exe
; 관리자 권한 없이 사용자 폴더(%LOCALAPPDATA%\Programs\SeomuAI)에 설치한다:
; 업무용 PC에서 관리자 권한이 없어도 설치되고, 프로그램 폴더의 models·engine에 파일을 받을 수 있다.

#ifndef AppVer
  #define AppVer "1.0.0"
#endif

[Setup]
AppId={{6C3B0E52-7A4D-4C1E-9B2F-5E1D2A9C7F31}
AppName=서무비서 AI
AppVersion={#AppVer}
AppPublisher=서무비서 AI
DefaultDirName={localappdata}\Programs\SeomuAI
DefaultGroupName=서무비서 AI
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SeomuAI-Setup
SetupIconFile=..\seomu\assets\app.ico
UninstallDisplayIcon={app}\SeomuAI.exe
UninstallDisplayName=서무비서 AI
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\Korean.isl")
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "..\dist\SeomuAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\서무비서 AI"; Filename: "{app}\SeomuAI.exe"
Name: "{autodesktop}\서무비서 AI"; Filename: "{app}\SeomuAI.exe"; Tasks: desktopicon

[Run]
; 설치가 끝나면 바로 실행 (마침 화면의 체크 상자, 기본 선택)
Filename: "{app}\SeomuAI.exe"; Description: "서무비서 AI 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 프로그램이 실행 중 만든 엔진 기록 파일만 지운다. 받아 둔 AI 모델(models)은 다시 받는 데 오래 걸려 남긴다
Type: files; Name: "{app}\engine\*.log"
