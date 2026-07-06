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

docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
wait_for_postgres

for migration in \
  drizzle/0037_tenant_integrity_and_scale.sql \
  drizzle/0038_cognitive_foundation_v2.sql; do
  docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < "${migration}"
done

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < ops/sql/preflight_tenant_integrity.sql

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < drizzle/0039_cognitive_tenant_rls.sql

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < drizzle/0040_agent_engine_v2.sql

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  < drizzle/0041_continuous_learning_v2.sql

RLS_ACTION="DISABLE"
RLS_FORCE_ACTION="NO FORCE"
if [[ "${ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED:-false}" == "true" ]]; then
  RLS_ACTION="ENABLE"
  RLS_FORCE_ACTION="FORCE"
fi

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<SQL
ALTER TABLE brain_memory_facts ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE brain_memory_episodes ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE dialogue_states ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE cognitive_memory_revisions ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE cognitive_mutation_outbox ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_runs ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_steps ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_evidence ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_events ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE continuous_learning_runs ${RLS_ACTION} ROW LEVEL SECURITY;
ALTER TABLE brain_memory_facts ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE brain_memory_episodes ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE dialogue_states ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE cognitive_memory_revisions ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE cognitive_mutation_outbox ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_runs ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_steps ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_evidence ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE agent_events ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
ALTER TABLE continuous_learning_runs ${RLS_FORCE_ACTION} ROW LEVEL SECURITY;
SQL

echo "Cognitive foundation schema bootstrap complete (RLS ${RLS_ACTION})."
