#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@84.247.172.213}"
REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://api.elyan.dev}"
DIRECT_HEALTHCHECK_URL="${DIRECT_HEALTHCHECK_URL:-http://84.247.172.213:4000/healthz}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BACKUP_DIR="${REMOTE_DIR}/.codex-backups/${STAMP}-v1-release"
APPLE_PRIVATE_KEY_SOURCE="${APPLE_PRIVATE_KEY_SOURCE:-}"
REMOTE_APPLE_PRIVATE_KEY="${REMOTE_DIR}/secrets/apple-iap-private-key.p8"
TEMP_ENV_CREATED="false"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need npm
need ssh
need rsync
need scp
need curl

cleanup() {
  if [[ "${TEMP_ENV_CREATED}" == "true" ]]; then
    rm -f .env
  fi
}

trap cleanup EXIT

probe_with_retry() {
  local attempts="${1:-6}"
  local delay_seconds="${2:-5}"
  local attempt=1

  while (( attempt <= attempts )); do
    if BASE_URL="${PUBLIC_BASE_URL}" DIRECT_HEALTHCHECK_URL="${DIRECT_HEALTHCHECK_URL}" bash scripts/probe-v1-runtime-flow.sh; then
      return 0
    fi

    if (( attempt == attempts )); then
      return 1
    fi

    echo "Probe attempt ${attempt}/${attempts} failed; waiting ${delay_seconds}s before retry."
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done
}

echo "==> Local gate"
ONNXRUNTIME_NODE_INSTALL=skip npm ci
if [[ ! -f .env ]]; then
  cp .env.example .env
  TEMP_ENV_CREATED="true"
fi
npm run build
npm test

echo "==> Remote backup to ${BACKUP_DIR}"
ssh "${REMOTE_HOST}" "umask 077 && install -d -m 700 '${BACKUP_DIR}' && cd '${REMOTE_DIR}' && tar --exclude='./.codex-backups' --exclude='./.codex-worktrees' --exclude='./node_modules' --exclude='./dist' --exclude='./.blob-store' --exclude='./.git' --exclude='./docs/release/evidence' --exclude='./.claude' --exclude='./.DS_Store' --exclude='*/__pycache__' -czf '${BACKUP_DIR}/release-source.tgz' . && sha256sum '${BACKUP_DIR}/release-source.tgz' > '${BACKUP_DIR}/release-source.tgz.sha256'"

echo "==> Sync release candidate"
rsync -az --delete \
  --exclude node_modules \
  --exclude dist \
  --exclude .git \
  --exclude .codex-backups \
  --exclude .codex-worktrees \
  --exclude .blob-store \
  --exclude .DS_Store \
  --exclude .claude \
  --exclude docs/release/evidence \
  --exclude '__pycache__' \
  --exclude '*.py[co]' \
  --exclude .env \
  --include .env.example \
  --exclude '.env.*' \
  --exclude secrets \
  ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "==> Remove stale generated and deployment-only files"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && rm -rf -- dist docs/release/evidence .claude ml-worker/__pycache__ && rm -f -- .DS_Store"

echo "==> Provision Apple IAP signing key"
if [[ -n "${APPLE_PRIVATE_KEY_SOURCE}" ]]; then
  if [[ ! -r "${APPLE_PRIVATE_KEY_SOURCE}" ]]; then
    echo "Apple IAP private key is not readable: ${APPLE_PRIVATE_KEY_SOURCE}" >&2
    exit 1
  fi
  ssh "${REMOTE_HOST}" "install -d -m 700 '${REMOTE_DIR}/secrets'"
  scp -q "${APPLE_PRIVATE_KEY_SOURCE}" "${REMOTE_HOST}:${REMOTE_APPLE_PRIVATE_KEY}.tmp"
  ssh "${REMOTE_HOST}" "install -m 600 '${REMOTE_APPLE_PRIVATE_KEY}.tmp' '${REMOTE_APPLE_PRIVATE_KEY}' && rm -f '${REMOTE_APPLE_PRIVATE_KEY}.tmp'"
else
  ssh "${REMOTE_HOST}" "test -r '${REMOTE_APPLE_PRIVATE_KEY}'" || {
    echo "Apple IAP private key is missing on the server. Set APPLE_PRIVATE_KEY_SOURCE for the deploy." >&2
    exit 1
  }
fi

echo "==> Remote install and test"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && ONNXRUNTIME_NODE_INSTALL=skip npm ci && npm run compile:nlp && npm run build && npm test"

echo "==> Remote schema bootstrap and restart"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && docker compose -f '${COMPOSE_FILE}' up -d postgres redis && bash scripts/bootstrap-v1-social-auth-schema.sh && bash scripts/bootstrap-v1-device-schema.sh && bash scripts/bootstrap-v2-apple-billing-schema.sh && bash scripts/bootstrap-v3-blob-memory-schema.sh && bash scripts/bootstrap-v4-identity-quota-schema.sh && bash scripts/bootstrap-v5-world-signals-schema.sh && bash scripts/bootstrap-v6-operator-schema.sh && bash scripts/bootstrap-v7-subscription-lifecycle-schema.sh && bash scripts/bootstrap-v8-session-goals-schema.sh && bash scripts/bootstrap-v9-agent-foundation-schema.sh && bash scripts/bootstrap-v10-cognitive-foundation-schema.sh && bash scripts/bootstrap-v11-integration-apps-schema.sh && bash scripts/bootstrap-v12-approval-policy-schema.sh && bash scripts/bootstrap-v13-web-schema.sh && docker compose -f '${COMPOSE_FILE}' up -d --build --remove-orphans"

echo "==> Post-deploy probe"
probe_with_retry 6 5

cat <<EOF
Rollback backup created at:
  ${BACKUP_DIR}

Rollback outline:
  1. ssh ${REMOTE_HOST}
  2. cd ${REMOTE_DIR}
  3. verify ${BACKUP_DIR}/release-source.tgz against release-source.tgz.sha256
  4. extract release-source.tgz into ${REMOTE_DIR}
  5. docker compose -f ${COMPOSE_FILE} up -d --build --remove-orphans
EOF
