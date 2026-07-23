#!/usr/bin/env bash
set -euo pipefail

lsof -nP -iTCP:8000 -sTCP:LISTEN || true
