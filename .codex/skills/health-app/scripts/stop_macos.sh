#!/usr/bin/env bash
set -euo pipefail

PIDS="$(lsof -tiTCP:8000 -sTCP:LISTEN || true)"

if [[ -z "${PIDS}" ]]; then
  echo "服务未运行。"
  exit 0
fi

echo "${PIDS}" | xargs kill
echo "服务已停止。"
