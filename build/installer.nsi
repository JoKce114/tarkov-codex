Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma
Name "塔科夫百科"
Caption "塔科夫百科 安装"
UninstallCaption "塔科夫百科 卸载"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\TarkovCodex"
InstallDirRegKey HKCU "Software\TarkovCodex" "InstallDir"
Icon "${APPICON}"
UninstallIcon "${APPICON}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "塔科夫百科"
VIAddVersionKey /LANG=2052 "FileDescription" "塔科夫百科安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "塔科夫百科"

!include "MUI2.nsh"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "欢迎安装塔科夫百科"
!define MUI_WELCOMEPAGE_TEXT "安装向导将引导您安装或升级塔科夫百科 ${VERSION}。$\r$\n$\r$\n从 ZIP 便携版升级时，请在下一页选择原程序所在目录，以迁移已有游戏资料与任务进度。"
!define MUI_UNCONFIRMPAGE_TEXT_TOP "卸载向导将移除塔科夫百科的程序文件。个人设置、游戏资料和任务进度会保留在本机。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"

!macro CheckClosed
checkRunning:
	System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Global\TarkovCodexSingleInstance") p.r0'
	StrCmp $0 0 ready
	System::Call 'kernel32::CloseHandle(p r0)'
	MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "请关闭正在运行的塔科夫百科，然后点击「重试」。" /SD IDCANCEL IDRETRY checkRunning
	Abort
ready:
!macroend

Section "安装程序"
	!insertmacro CheckClosed
	SetOutPath "$INSTDIR"
	SetOverwrite on
	File /r "${PAYLOAD}\*"
	WriteUninstaller "$INSTDIR\卸载塔科夫百科.exe"
	WriteRegStr HKCU "Software\TarkovCodex" "InstallDir" "$INSTDIR"
	WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "DisplayName" "塔科夫百科"
	WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "DisplayVersion" "${VERSION}"
	WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "InstallLocation" "$INSTDIR"
	WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "DisplayIcon" "$INSTDIR\塔科夫百科.exe"
	WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "UninstallString" '"$INSTDIR\卸载塔科夫百科.exe"'
	WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "NoModify" 1
	WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex" "NoRepair" 1
	CreateShortcut "$SMPROGRAMS\塔科夫百科.lnk" "$INSTDIR\塔科夫百科.exe"
SectionEnd

Section "Uninstall"
	!insertmacro CheckClosed
	!include "${UNINSTALL_FILES}"
	Delete "$INSTDIR\卸载塔科夫百科.exe"
	Delete "$SMPROGRAMS\塔科夫百科.lnk"
	DeleteRegKey HKCU "Software\TarkovCodex"
	DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TarkovCodex"
	RMDir "$INSTDIR"
SectionEnd
