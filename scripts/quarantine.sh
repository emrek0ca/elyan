#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d)"
TARGET_DIR="$ROOT_DIR/_graveyard/$STAMP"

mkdir -p "$TARGET_DIR"

move_if_exists() {
  local rel="$1"
  local src="$ROOT_DIR/$rel"
  if [[ -e "$src" ]]; then
    mv "$src" "$TARGET_DIR/"
    echo "[QUARANTINE] $rel -> _graveyard/$STAMP/"
  fi
}

move_if_exists "tmpdir"
move_if_exists ".pytest_cache"
move_if_exists "logs"

echo "[QUARANTINE] tamamlandı: $TARGET_DIR"

