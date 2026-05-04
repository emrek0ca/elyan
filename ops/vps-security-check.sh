#!/bin/bash
set -euo pipefail

DEPLOY_ROOT="${ELYAN_DEPLOY_ROOT:-/srv/elyan}"
ENV_FILE="${ELYAN_ENV_FILE:-${DEPLOY_ROOT}/.env}"
SERVICE_NAME="${ELYAN_SERVICE_NAME:-elyan}"
CURRENT_LINK="${DEPLOY_ROOT}/current"
RELEASES_DIR="${DEPLOY_ROOT}/releases"
STORAGE_DIR="${ELYAN_STORAGE_DIR:-${DEPLOY_ROOT}/storage}"

failures=0

check() {
    local label="$1"
    shift

    if "$@"; then
        echo "ok: ${label}"
    else
        echo "fail: ${label}"
        failures=$((failures + 1))
    fi
}

is_not_group_or_world_writable() {
    local target="$1"
    local mode
    local group_digit
    local world_digit
    mode="$(stat -c '%a' "$target" 2>/dev/null || stat -f '%Lp' "$target")"
    group_digit=$(((mode / 10) % 10))
    world_digit=$((mode % 10))
    [ $((group_digit & 2)) -eq 0 ] && [ $((world_digit & 2)) -eq 0 ]
}

is_env_private() {
    local mode
    mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")"
    [ "$mode" -le 640 ]
}

current_points_to_release() {
    [ -L "$CURRENT_LINK" ] && readlink "$CURRENT_LINK" | grep -q "^${RELEASES_DIR}/"
}

docker_postgres_is_publicly_blocked() {
    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi

    if ! docker ps --format '{{.Ports}}' | grep -q '0.0.0.0:5432->5432/tcp'; then
        return 0
    fi

    iptables -S DOCKER-USER 2>/dev/null | grep -- '--dport 5432' | grep -q -- '-j DROP'
}

echo "Elyan VPS security check"
echo "No secrets are printed by this script."
echo

check "deploy root exists" test -d "$DEPLOY_ROOT"
check "releases directory exists" test -d "$RELEASES_DIR"
check "storage directory exists" test -d "$STORAGE_DIR"
check "env file exists" test -f "$ENV_FILE"
check "env file mode is 640 or stricter" is_env_private
check "deploy root is not group/world writable" is_not_group_or_world_writable "$DEPLOY_ROOT"
check "storage is not group/world writable" is_not_group_or_world_writable "$STORAGE_DIR"
check "current symlink points inside releases" current_points_to_release
check "systemd service exists" systemctl cat "$SERVICE_NAME" >/dev/null
check "systemd service is enabled" systemctl is-enabled "$SERVICE_NAME" >/dev/null
check "systemd service is active" systemctl is-active "$SERVICE_NAME" >/dev/null
check "public Docker PostgreSQL exposure is blocked" docker_postgres_is_publicly_blocked

if [ "$failures" -gt 0 ]; then
    echo
    echo "Security check completed with ${failures} failure(s)."
    exit 1
fi

echo
echo "VPS security check passed."
