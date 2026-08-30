#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@84.247.172.213}"
REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://api.elyan.dev}"
DIRECT_HEALTHCHECK_URL="${DIRECT_HEALTHCHECK_URL:-http://84.247.172.213:4000/healthz}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BACKUP_DIR="${REMOTE_DIR}/.codex-backups/${STAMP}-v1-release"
APPLE_IAP_PRIVATE_KEY_SOURCE="${APPLE_IAP_PRIVATE_KEY_SOURCE:-${APPLE_PRIVATE_KEY_SOURCE:-}}"
APNS_PRIVATE_KEY_SOURCE="${APNS_PRIVATE_KEY_SOURCE:-}"
REMOTE_APPLE_PRIVATE_KEY="${REMOTE_DIR}/secrets/apple-iap-private-key.p8"
REMOTE_APNS_PRIVATE_KEY="${REMOTE_DIR}/secrets/apns-private-key.p8"
TEMP_ENV_CREATED="false"
# YEREL KAPI ATLANABİLİR OLMALI.
#
# Kapı `npm test`i çağırıyor ve o paket 293 dosyayı tek seferde koşturduğu için
# GÜVENİLİR biçimde asılıyordu (bkz. scripts/run-tests.sh). Deploy iki kez
# burada durdu ve uzak adımlar elle yürütüldü — o elle yol hiçbir yerde yazılı
# değildi, her seferinde hafızadan kuruldu. Artık birinci sınıf:
#
#   --skip-local-gate   yerel test kapısını atla (derleme yine koşar)
#   --remote-only       yerel adımların tamamını atla, doğrudan sunucuya git
SKIP_LOCAL_GATE="false"
REMOTE_ONLY="false"
for arg in "$@"; do
  case "${arg}" in
    --skip-local-gate) SKIP_LOCAL_GATE="true" ;;
    --remote-only) REMOTE_ONLY="true"; SKIP_LOCAL_GATE="true" ;;
    --help|-h)
      echo "kullanım: bash scripts/deploy-v1-release.sh [--skip-local-gate] [--remote-only]"
      exit 0
      ;;
    *)
      echo "bilinmeyen argüman: ${arg}" >&2
      exit 1
      ;;
  esac
done

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
need openssl

run_remote() {
  local command="$1"
  local attempt=1
  local max_attempts=5
  local delay_seconds=5
  local status=0

  while (( attempt <= max_attempts )); do
    if ssh -o ConnectTimeout=15 "${REMOTE_HOST}" "${command}"; then
      return 0
    else
      status=$?
    fi
    if [[ "${status}" -ne 255 || "${attempt}" -eq "${max_attempts}" ]]; then
      return "${status}"
    fi
    echo "SSH transport failed (attempt ${attempt}/${max_attempts}); retrying in ${delay_seconds}s." >&2
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
    delay_seconds=$((delay_seconds < 30 ? delay_seconds * 2 : 30))
  done
}

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

provision_private_key() {
  local label="$1"
  local source="$2"
  local remote_path="$3"
  local remote_tmp="${remote_path}.${STAMP}.tmp"

  if [[ -n "${source}" ]]; then
    if [[ ! -f "${source}" || ! -s "${source}" || ! -r "${source}" ]]; then
      echo "${label} private key must be a readable, non-empty regular file: ${source}" >&2
      exit 1
    fi
    if ! openssl pkey -in "${source}" -check -noout >/dev/null 2>&1; then
      echo "${label} private key is not a valid private key: ${source}" >&2
      exit 1
    fi
    run_remote "install -d -m 700 '${REMOTE_DIR}/secrets' && rm -f -- '${remote_tmp}'"
    scp -q "${source}" "${REMOTE_HOST}:${remote_tmp}"
    run_remote "if test -d '${remote_path}'; then rmdir -- '${remote_path}'; fi && install -m 600 '${remote_tmp}' '${remote_path}' && rm -f -- '${remote_tmp}' && test -f '${remote_path}' && test -s '${remote_path}'"
    return
  fi

  run_remote "test -f '${remote_path}' && test -s '${remote_path}'" || {
    echo "${label} private key is missing on the server. Provide its deploy source." >&2
    exit 1
  }
}

if [[ "${REMOTE_ONLY}" == "true" ]]; then
  echo "==> Yerel adımlar atlandı (--remote-only)"
else
  echo "==> Local gate"
  ONNXRUNTIME_NODE_INSTALL=skip npm ci
  if [[ ! -f .env ]]; then
    cp .env.example .env
    TEMP_ENV_CREATED="true"
  fi
  npm run build
  if [[ "${SKIP_LOCAL_GATE}" == "true" ]]; then
    echo "==> Yerel test kapısı ATLANDI (--skip-local-gate)"
    echo "    Doğrulama çağıranın sorumluluğunda: bash scripts/run-tests.sh"
  else
    npm test
  fi
fi

echo "==> Remote backup to ${BACKUP_DIR}"
run_remote "umask 077 && install -d -m 700 '${BACKUP_DIR}' && cd '${REMOTE_DIR}' && tar --exclude='./.codex-backups' --exclude='./.codex-worktrees' --exclude='./node_modules' --exclude='./dist' --exclude='./.blob-store' --exclude='./.semantic-model-cache' --exclude='./.git' --exclude='./docs/release/evidence' --exclude='./.claude' --exclude='./.DS_Store' --exclude='*/__pycache__' -czf '${BACKUP_DIR}/release-source.tgz' . && sha256sum '${BACKUP_DIR}/release-source.tgz' > '${BACKUP_DIR}/release-source.tgz.sha256'"

echo "==> Sync release candidate"
rsync -az --delete \
  --exclude node_modules \
  --exclude dist \
  --exclude .git \
  --exclude .codex-backups \
  --exclude .codex-worktrees \
  --exclude .blob-store \
  --exclude .semantic-model-cache \
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
run_remote "cd '${REMOTE_DIR}' && rm -rf -- dist docs/release/evidence .claude ml-worker/__pycache__ && rm -f -- .DS_Store"

echo "==> Provision Apple signing keys"
provision_private_key "Apple IAP" "${APPLE_IAP_PRIVATE_KEY_SOURCE}" "${REMOTE_APPLE_PRIVATE_KEY}"
provision_private_key "APNs" "${APNS_PRIVATE_KEY_SOURCE}" "${REMOTE_APNS_PRIVATE_KEY}"

if [[ "${SKIP_LOCAL_GATE}" == "true" ]]; then
  # Uzak kapı da aynı `npm test`i çağırıyor ve aynı sebeple asılabilir.
  # Bayrak ikisini birden kapatır; yarısını atlamak yanıltıcı olurdu.
  echo "==> Remote install (test kapısı atlandı)"
  run_remote "cd '${REMOTE_DIR}' && ONNXRUNTIME_NODE_INSTALL=skip npm ci && npm run compile:nlp && npm run build"
else
  echo "==> Remote install and test"
  run_remote "cd '${REMOTE_DIR}' && ONNXRUNTIME_NODE_INSTALL=skip npm ci && npm run compile:nlp && npm run build && npm test"
fi

echo "==> Remote schema bootstrap and restart"
run_remote "cd '${REMOTE_DIR}' && docker compose -f '${COMPOSE_FILE}' up -d postgres redis && bash scripts/bootstrap-all.sh && docker compose -f '${COMPOSE_FILE}' up -d --build --remove-orphans"

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
