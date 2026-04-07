#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${ELYAN_PORT:-18789}"

cd "$ROOT_DIR"
python3 -m cli.main gateway start --daemon --port "$PORT"
exec python3 -m cli.main desktop "$@"
