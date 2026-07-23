#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
PYTHON_BIN="${HEALTH_PYTHON_BIN:-$(command -v python3.12 || true)}"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.health-vault-agent.plist"
LOG_DIR="${HOME}/Library/Logs/HealthVaultAgent"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "未找到 python3.12，请先安装 Python 3.12。" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"

cat >"${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.health-vault-agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_ROOT}/backend</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/com.health-vault-agent"
launchctl kickstart -k "gui/$(id -u)/com.health-vault-agent"

echo "已注册 macOS 登录自启：com.health-vault-agent"
echo "项目路径：${PROJECT_ROOT}"
echo "Python：${PYTHON_BIN}"
echo "plist：${PLIST_PATH}"
