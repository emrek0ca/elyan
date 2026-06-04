#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELECTRON_DIR="$ROOT_DIR/electron"
APP_NAME="Elyan"
PYTHON_EXECUTABLE="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"

set_runtime_env() {
  export ELYAN_ROOT="$ROOT_DIR"
  if [ -n "$PYTHON_EXECUTABLE" ]; then
    export ELYAN_PYTHON="$PYTHON_EXECUTABLE"
    export ELYAN_PYTHON_BIN="$PYTHON_EXECUTABLE"
    export ELYAN_DESKTOP_PYTHON="$PYTHON_EXECUTABLE"
  fi
  if [ -z "${APP_BASE_URL:-}" ] && [ -n "$PYTHON_EXECUTABLE" ]; then
    APP_BASE_URL="$(
      cd "$ROOT_DIR" && "$PYTHON_EXECUTABLE" - <<'PY'
from app_config import get_app_config_value
value = str(get_app_config_value("backend_base_url", "") or "").strip()
print(value)
PY
    )"
    APP_BASE_URL="$(printf '%s' "$APP_BASE_URL" | tr -d '\r\n')"
  fi
  if [ -n "${APP_BASE_URL:-}" ]; then
    export APP_BASE_URL
  fi
  if [ "$(uname -s)" = "Darwin" ]; then
    /bin/launchctl setenv ELYAN_ROOT "$ROOT_DIR" >/dev/null 2>&1 || true
    if [ -n "$PYTHON_EXECUTABLE" ]; then
      /bin/launchctl setenv ELYAN_PYTHON "$PYTHON_EXECUTABLE" >/dev/null 2>&1 || true
      /bin/launchctl setenv ELYAN_PYTHON_BIN "$PYTHON_EXECUTABLE" >/dev/null 2>&1 || true
      /bin/launchctl setenv ELYAN_DESKTOP_PYTHON "$PYTHON_EXECUTABLE" >/dev/null 2>&1 || true
    fi
    if [ -n "${APP_BASE_URL:-}" ]; then
      /bin/launchctl setenv APP_BASE_URL "$APP_BASE_URL" >/dev/null 2>&1 || true
    fi
  fi
}

ensure_electron_ready() {
  if [ ! -d "$ELECTRON_DIR" ]; then
    echo "Electron desktop directory not found: $ELECTRON_DIR" >&2
    exit 2
  fi
  if [ ! -d "$ELECTRON_DIR/node_modules" ]; then
    echo "Electron dependencies missing. Run: cd $ELECTRON_DIR && npm install" >&2
    exit 2
  fi
}

kill_existing() {
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  pkill -x Electron >/dev/null 2>&1 || true
}

run_app() {
  set_runtime_env
  ensure_electron_ready
  (cd "$ELECTRON_DIR" && npm run dev)
}

debug_app() {
  set_runtime_env
  ensure_electron_ready
  export ELECTRON_ENABLE_LOGGING=1
  export ELECTRON_ENABLE_STACK_DUMPING=1
  (cd "$ELECTRON_DIR" && npm run dev)
}

stream_logs() {
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "System log streaming is only supported on macOS. Use npm run dev for foreground logs." >&2
    exit 2
  fi
  /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\" OR process == \"Electron\""
}

verify_app() {
  set_runtime_env
  ensure_electron_ready
  (
    cd "$ELECTRON_DIR"
    npm run typecheck
    npm run test
    npm run build
    npm run test:smoke
  )
}

case "$MODE" in
  run)
    kill_existing
    run_app
    ;;
  --debug|debug)
    kill_existing
    debug_app
    ;;
  --logs|logs)
    stream_logs
    ;;
  --telemetry|telemetry)
    stream_logs
    ;;
  --verify|verify)
    verify_app
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
