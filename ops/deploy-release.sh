#!/bin/bash
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "Usage: ./ops/deploy-release.sh <version>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_ROOT="${ELYAN_DEPLOY_ROOT:-/srv/elyan}"
RELEASES_DIR="${DEPLOY_ROOT}/releases"
CURRENT_LINK="${DEPLOY_ROOT}/current"
CURRENT_RELEASE_FILE="${DEPLOY_ROOT}/.release-current"
PREVIOUS_RELEASE_FILE="${DEPLOY_ROOT}/.release-previous"
ENV_FILE="${ELYAN_ENV_FILE:-${DEPLOY_ROOT}/.env}"
STORAGE_DIR="${ELYAN_STORAGE_DIR:-${DEPLOY_ROOT}/storage}"
SERVICE_NAME="${ELYAN_SERVICE_NAME:-elyan}"
EXPECTED_RELEASE_DIR="${RELEASES_DIR}/${VERSION}"

echo "======================================"
echo " Deploying Elyan release ${VERSION} "
echo "======================================"

if [ "$RELEASE_DIR" != "$EXPECTED_RELEASE_DIR" ]; then
    echo "[!] CRITICAL: Release extracted to $RELEASE_DIR, expected $EXPECTED_RELEASE_DIR"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[!] CRITICAL: Missing Elyan env file at $ENV_FILE"
    exit 1
fi

set -a
. "$ENV_FILE"
set +a

mkdir -p "$RELEASES_DIR" "$STORAGE_DIR/control-plane" "$STORAGE_DIR/runtime"

PREVIOUS_TARGET=""
if [ -L "$CURRENT_LINK" ]; then
    PREVIOUS_TARGET="$(readlink "$CURRENT_LINK")"
fi

cd "$RELEASE_DIR"
npm ci
npm run db:migrate
npm run build

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
systemctl restart "$SERVICE_NAME"

if "$SCRIPT_DIR/healthcheck.sh"; then
    printf '%s\n' "$PREVIOUS_TARGET" > "$PREVIOUS_RELEASE_FILE"
    printf '%s\n' "$RELEASE_DIR" > "$CURRENT_RELEASE_FILE"
    echo "======================================"
    echo "✅ Elyan ${VERSION} deployed successfully."
    echo "======================================"
    exit 0
fi

echo "======================================"
echo "❌ Deploy healthcheck failed. Reverting."
echo "======================================"

if [ -n "$PREVIOUS_TARGET" ] && [ -d "$PREVIOUS_TARGET" ]; then
    ln -sfn "$PREVIOUS_TARGET" "$CURRENT_LINK"
    systemctl restart "$SERVICE_NAME"

    if "${PREVIOUS_TARGET}/ops/healthcheck.sh"; then
        printf '%s\n' "$PREVIOUS_TARGET" > "$CURRENT_RELEASE_FILE"
        echo "✅ Automatic rollback restored the previous healthy release."
        exit 1
    fi
fi

echo "❌ Automatic rollback could not restore a healthy Elyan release."
journalctl -u "$SERVICE_NAME" --no-pager -n 80 || true
exit 1
