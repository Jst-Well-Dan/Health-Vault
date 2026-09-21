param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $ProjectPath "package.json"))) {
    throw "项目目录无效：$ProjectPath"
}

$venvPython = Join-Path $ProjectPath ".venv\Scripts\python.exe"
if (Test-Path $venvPython) { $env:HEALTH_PYTHON = $venvPython }
$bindHost = [Environment]::GetEnvironmentVariable("HEALTH_HOST", "User")
if ($bindHost) { $env:HEALTH_HOST = $bindHost }

Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run start" -WorkingDirectory $ProjectPath -WindowStyle Hidden
