#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="$ROOT_DIR/apps/macos/ElyanMac/ElyanMac.xcodeproj"
DERIVED_DATA_PATH="$ROOT_DIR/apps/macos/ElyanMac/build-release"
APP_PATH="$DERIVED_DATA_PATH/Build/Products/Release/Elyan.app"
APP_NAME="Elyan"
TARGET_NAME="ElyanMac"

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: %s [--verify|--logs]\n' "$0"
  exit 0
fi

pkill -x "$APP_NAME" 2>/dev/null || true
pkill -x "ElyanMac" 2>/dev/null || true

rm -rf "$DERIVED_DATA_PATH"

xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$TARGET_NAME" \
  -configuration Release \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  build \
  CODE_SIGNING_ALLOWED=NO

rm -rf "$DERIVED_DATA_PATH/Build/Products/Release/ElyanMac.app"

/usr/bin/open -n "$APP_PATH"

if [[ "${1:-}" == "--verify" ]]; then
  for _ in {1..20}; do
    if pgrep -x "$APP_NAME" >/dev/null && pgrep -fl "runtime/bridge.py" >/dev/null; then
      break
    fi
    sleep 1
  done
  pgrep -x "$APP_NAME" >/dev/null
  pgrep -fl "runtime/bridge.py" >/dev/null
fi

if [[ "${1:-}" == "--logs" ]]; then
  /usr/bin/log stream --info --predicate 'process == "Elyan"'
fi
