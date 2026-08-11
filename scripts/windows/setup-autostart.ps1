﻿param(
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
$taskName = "HealthVaultWeb"
$launcher = (Resolve-Path (Join-Path $PSScriptRoot "start-hidden.ps1")).Path
$project = (Resolve-Path $ProjectPath).Path

if (-not [Environment]::GetEnvironmentVariable("HEALTH_APP_PASSWORD", "User")) {
    throw "请先在 Windows 用户环境变量中设置 HEALTH_APP_PASSWORD，再启用开机自启。"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" -ProjectPath `"$project`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Output "已注册 Windows 登录自启：$taskName"
