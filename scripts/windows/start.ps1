﻿param(
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $ProjectPath "package.json"))) {
    throw "项目目录无效：$ProjectPath"
}
if (-not $env:HEALTH_APP_PASSWORD) {
    throw "请先设置 HEALTH_APP_PASSWORD（家庭共享密码）。"
}

Set-Location $ProjectPath
npm run start
