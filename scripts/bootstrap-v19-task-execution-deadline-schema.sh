#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-elyan_backend}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
for attempt in $(seq 1 30); do
  if docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    exit 1
  fi
  sleep 2
done

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < drizzle/0058_task_execution_deadlines.sql
