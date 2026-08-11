#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
LABEL="com.healthvault.web"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/HealthVaultWeb"
KEYCHAIN_SERVICE="HealthVaultWeb"
PYTHON_BIN="${HEALTH_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "未找到可执行 Python：${PYTHON_BIN}。请先创建 .venv，或设置 HEALTH_PYTHON。" >&2
  exit 1
fi

if [[ -z "${HEALTH_APP_PASSWORD:-}" ]]; then
  read -r -s -p "设置家庭共享密码（至少 12 个字符）：" HEALTH_APP_PASSWORD
  echo
fi
if [[ ${#HEALTH_APP_PASSWORD} -lt 12 ]]; then
  echo "家庭共享密码至少需要 12 个字符。" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"
security add-generic-password -U -a "${USER}" -s "${KEYCHAIN_SERVICE}" -w "${HEALTH_APP_PASSWORD}"

cat >"${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SCRIPT_DIR}/start-launchagent.sh</string>
    <string>${PROJECT_ROOT}</string>
    <string>${PYTHON_BIN}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/app.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/app.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "已注册 macOS 登录自启：${LABEL}"
