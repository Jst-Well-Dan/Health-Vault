param(
    [string]$TargetPath = "E:\Python_Doc\My_Github\Health-Vault-Public"
)

$ErrorActionPreference = "Stop"
$sourcePath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targetPath = [System.IO.Path]::GetFullPath($TargetPath)
if (Test-Path $targetPath) {
    throw "目标目录已存在：$targetPath"
}

New-Item -ItemType Directory -Path $targetPath | Out-Null
$files = & git -C $sourcePath ls-files --cached --others --exclude-standard
$excluded = '^(data/|\.pi-subagents/|\.stfolder/)|(^|/)\.DS_Store$|(^|/)\.env(?:\.|$)|\.sync-conflict-'
$copied = 0
foreach ($relativePath in $files) {
    if ($relativePath -match $excluded) { continue }
    $sourceFile = Join-Path $sourcePath $relativePath
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { continue }
    $targetFile = Join-Path $targetPath $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetFile) | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $targetFile
    $copied++
}

Push-Location $targetPath
try {
    git init -b main | Out-Null
    git add --all
    git update-index --chmod=+x scripts/macos/start.sh scripts/macos/start-launchagent.sh scripts/macos/setup-autostart.sh scripts/macos/remove-autostart.sh
    git commit -m "Initial public release" | Out-Null
} finally {
    Pop-Location
}

Write-Output "已创建无历史公开仓库：$targetPath（复制 $copied 个文件）。尚未配置远端或推送。"
