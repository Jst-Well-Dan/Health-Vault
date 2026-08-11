#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

if [[ -z "${HEALTH_APP_PASSWORD:-}" ]]; then
  echo "请先设置 HEALTH_APP_PASSWORD（家庭共享密码）。" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"
exec npm run start
