#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$1"
PYTHON_BIN="$2"
KEYCHAIN_SERVICE="HealthVaultWeb"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HEALTH_APP_PASSWORD="$(security find-generic-password -a "${USER}" -s "${KEYCHAIN_SERVICE}" -w)"
if [[ -z "${HEALTH_APP_PASSWORD}" ]]; then
  echo "未在 macOS 钥匙串中找到家庭共享密码。" >&2
  exit 1
fi

export HEALTH_PYTHON="${PYTHON_BIN}"
cd "${PROJECT_ROOT}"
exec npm run start
