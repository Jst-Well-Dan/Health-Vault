#!/usr/bin/env bash
set -euo pipefail

PLIST_PATH="${HOME}/Library/LaunchAgents/com.health-vault-agent.plist"

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
rm -f "${PLIST_PATH}"

echo "已移除 macOS 登录自启：com.health-vault-agent"
