#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-elyan_backend}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

wait_for_postgres() {
  local attempts="${1:-30}"
  local delay_seconds="${2:-2}"
  local attempt=1

  while (( attempt <= attempts )); do
    if docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
      pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done

  echo "PostgreSQL did not become ready in time." >&2
  exit 1
}

echo "==> Ensuring PostgreSQL is up"
docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
wait_for_postgres

echo "==> Bootstrapping agent foundation schema"
for migration in \
  drizzle/0029_turn_metrics.sql \
  drizzle/0030_dialogue_states.sql \
  drizzle/0031_proactive_triggers.sql \
  drizzle/0032_single_value_memory.sql \
  drizzle/0033_goal_events.sql \
  drizzle/0034_user_proactive_prefs.sql \
  drizzle/0035_brain_memory_semantic_v2.sql \
  drizzle/0036_user_consents.sql; do
  docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    < "${migration}"
done
echo "==> Agent foundation schema bootstrap complete"
