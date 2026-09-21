#!/usr/bin/env bash
set -euo pipefail

LABEL="com.healthvault.web"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
KEYCHAIN_SERVICE="HealthVaultWeb"

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
rm -f "${PLIST_PATH}"
# 兼容清理：旧版本曾把家庭共享密码写进钥匙串，现已不再使用。
security delete-generic-password -a "${USER}" -s "${KEYCHAIN_SERVICE}" >/dev/null 2>&1 || true

echo "已移除 macOS 登录自启：${LABEL}"
