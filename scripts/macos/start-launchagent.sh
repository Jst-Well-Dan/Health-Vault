#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$1"
PYTHON_BIN="$2"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HEALTH_PYTHON="${PYTHON_BIN}"
cd "${PROJECT_ROOT}"
exec npm run start
