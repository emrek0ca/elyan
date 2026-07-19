#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-elyan_backend}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

wait_for_postgres() {
  local attempt=1
  while (( attempt <= 30 )); do
    if docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
      pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
}

echo "==> Ensuring PostgreSQL is up"
docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
wait_for_postgres

echo "==> Bootstrapping approval policy schema"
docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < drizzle/0045_user_approval_mode.sql
echo "==> Approval policy schema bootstrap complete"
