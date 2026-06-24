#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-elyan_backend}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

wait_for_postgres() {
  local attempts="${1:-30}"
  local delay_seconds="${2:-2}"
  local attempt=1

  while (( attempt <= attempts )); do
    if docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
      return 0
    fi

    if (( attempt == attempts )); then
      break
    fi

    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done

  echo "PostgreSQL did not become ready in time." >&2
  exit 1
}

run_psql() {
  docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
}

need docker

cd "${REMOTE_DIR}"

echo "==> Ensuring PostgreSQL is up"
docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
wait_for_postgres

echo "==> Bootstrapping device schema (client_metadata column)"
run_psql <<'SQL'
ALTER TABLE "devices" ADD COLUMN IF NOT EXISTS "client_metadata" jsonb DEFAULT '{}'::jsonb NOT NULL;
SQL

echo "==> Device schema bootstrap complete"
