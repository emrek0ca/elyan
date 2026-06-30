#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="$ROOT_DIR/apps/macos/ElyanMac/ElyanMac.xcodeproj"
DERIVED_DATA_PATH="$ROOT_DIR/apps/macos/ElyanMac/build-debug"
APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug/ElyanMac.app"
APP_NAME="ElyanMac"

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: %s [--verify|--logs]\n' "$0"
  exit 0
fi

pkill -x "$APP_NAME" 2>/dev/null || true

xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$APP_NAME" \
  -configuration Debug \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  build \
  CODE_SIGNING_ALLOWED=NO

/usr/bin/open -n "$APP_PATH"

if [[ "${1:-}" == "--verify" ]]; then
  sleep 3
  pgrep -x "$APP_NAME" >/dev/null
  pgrep -fl "runtime/bridge.py" >/dev/null
fi

if [[ "${1:-}" == "--logs" ]]; then
  /usr/bin/log stream --info --predicate 'process == "ElyanMac"'
fi
