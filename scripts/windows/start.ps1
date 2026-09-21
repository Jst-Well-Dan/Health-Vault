param(
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $ProjectPath "package.json"))) {
    throw "项目目录无效：$ProjectPath"
}

Set-Location $ProjectPath
npm run start
