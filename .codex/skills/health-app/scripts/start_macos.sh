#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
PYTHON_BIN="${HEALTH_PYTHON_BIN:-$(command -v python3.12 || true)}"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "未找到 python3.12，请先安装 Python 3.12。" >&2
  exit 1
fi

echo "正在前台启动家庭健康档案服务..."
cd "${PROJECT_ROOT}/backend"
exec "${PYTHON_BIN}" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
