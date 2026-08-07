Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectPath = WshShell.ExpandEnvironmentStrings("%HEALTH_PROJECT_PATH%")
If projectPath = "%HEALTH_PROJECT_PATH%" Then
    scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
    projectPath = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))))
End If
password = WshShell.ExpandEnvironmentStrings("%HEALTH_APP_PASSWORD%")
If password = "%HEALTH_APP_PASSWORD%" Or password = "" Then
    WScript.Echo "请先设置用户环境变量 HEALTH_APP_PASSWORD，再配置后台启动。"
    WScript.Quit 1
End If
WshShell.Run "cmd /c cd /d """ & projectPath & """ && set HEALTH_HOST=0.0.0.0 && npm run start", 0, False
