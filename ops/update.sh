#!/bin/bash
set -euo pipefail

echo "======================================"
echo " Starting Elyan VPS Update Strategy "
echo "======================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SERVICE_NAME="${ELYAN_SERVICE_NAME:-elyan}"
BRANCH="${ELYAN_RELEASE_BRANCH:-main}"

if [ ! -f ".env" ]; then
    echo "[!] CRITICAL: .env file is missing. Elyan cannot be updated safely without its own environment file."
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "[!] CRITICAL: Working tree is not clean. Commit or stash Elyan changes before updating."
    exit 1
fi

CURRENT_COMMIT=$(git rev-parse HEAD)
echo "$CURRENT_COMMIT" > .previous_elyan_commit

CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    git switch "$BRANCH"
fi

echo "Fetching latest Elyan commits..."
git fetch origin "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "Installing production dependencies..."
npm ci

echo "Applying hosted PostgreSQL migrations..."
npm run db:migrate

echo "Building the Elyan runtime..."
npm run build

echo "Restarting Elyan service: $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Verifying Elyan readiness probes..."
if "$SCRIPT_DIR/healthcheck.sh"; then
    echo "======================================"
    echo "✅ Update Successful. Elyan is healthy."
    echo "======================================"
else
    echo "======================================"
    echo "❌ CRITICAL FAULT: Elyan failed healthchecks."
    echo "Recommendation: Execute ./ops/rollback.sh immediately."
    echo "Recent Elyan logs:"
    journalctl -u "$SERVICE_NAME" --no-pager -n 80 || true
    echo "======================================"
    exit 1
fi
