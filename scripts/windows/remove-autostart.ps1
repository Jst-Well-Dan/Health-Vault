﻿$ErrorActionPreference = "Stop"
$taskName = "HealthVaultWeb"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "已移除 Windows 登录自启：$taskName"
