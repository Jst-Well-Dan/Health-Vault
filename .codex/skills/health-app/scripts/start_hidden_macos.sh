#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
PYTHON_BIN="${HEALTH_PYTHON_BIN:-$(command -v python3.12 || true)}"
LOG_PATH="${HEALTH_LOG_PATH:-${HOME}/Library/Logs/HealthVaultAgent/app.log}"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "未找到 python3.12，请先安装 Python 3.12。" >&2
  exit 1
fi

mkdir -p "$(dirname "${LOG_PATH}")"
cd "${PROJECT_ROOT}/backend"
nohup "${PYTHON_BIN}" -m uvicorn main:app --host 0.0.0.0 --port 8000 >"${LOG_PATH}" 2>&1 &
echo "已在后台启动，PID: $!"
echo "日志: ${LOG_PATH}"
