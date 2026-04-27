#!/bin/bash
set -euo pipefail

DEPLOY_ROOT="${ELYAN_DEPLOY_ROOT:-/srv/elyan}"
CURRENT_LINK="${DEPLOY_ROOT}/current"
PREVIOUS_RELEASE_FILE="${DEPLOY_ROOT}/.release-previous"
SERVICE_NAME="${ELYAN_SERVICE_NAME:-elyan}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ELYAN_ENV_FILE:-${DEPLOY_ROOT}/.env}"

echo "======================================"
echo " Rolling back Elyan release "
echo "======================================"

if [ ! -f "$PREVIOUS_RELEASE_FILE" ]; then
    echo "[!] CRITICAL: No previous Elyan release recorded."
    exit 1
fi

PREVIOUS_RELEASE="$(cat "$PREVIOUS_RELEASE_FILE")"
if [ -z "$PREVIOUS_RELEASE" ] || [ ! -d "$PREVIOUS_RELEASE" ]; then
    echo "[!] CRITICAL: Previous release path is missing: $PREVIOUS_RELEASE"
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

ln -sfn "$PREVIOUS_RELEASE" "$CURRENT_LINK"
systemctl restart "$SERVICE_NAME"

if "${PREVIOUS_RELEASE}/ops/healthcheck.sh"; then
    echo "======================================"
    echo "✅ Rollback executed. Elyan is healthy on the previous release."
    echo "======================================"
else
    echo "======================================"
    echo "❌ Rollback completed, but healthchecks are still failing."
    journalctl -u "$SERVICE_NAME" --no-pager -n 80 || true
    echo "======================================"
    exit 1
fi
