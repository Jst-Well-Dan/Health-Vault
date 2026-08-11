﻿param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $ProjectPath "package.json"))) {
    throw "项目目录无效：$ProjectPath"
}

$password = [Environment]::GetEnvironmentVariable("HEALTH_APP_PASSWORD", "User")
if (-not $password) {
    throw "请先设置用户环境变量 HEALTH_APP_PASSWORD，再启用开机自启。"
}
$env:HEALTH_APP_PASSWORD = $password
$venvPython = Join-Path $ProjectPath ".venv\Scripts\python.exe"
if (Test-Path $venvPython) { $env:HEALTH_PYTHON = $venvPython }
$host = [Environment]::GetEnvironmentVariable("HEALTH_HOST", "User")
if ($host) { $env:HEALTH_HOST = $host }

Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run start" -WorkingDirectory $ProjectPath -WindowStyle Hidden
