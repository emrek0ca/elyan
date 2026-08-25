#!/usr/bin/env bash
set -euo pipefail

# v17 — TİPLİ EPİZOT AMBARI ve ARADA KALMIŞ MIGRATION'LAR.
#
# 0052/0053/0054 hiçbir bootstrap tarafından uygulanmıyordu: deploy hattı
# bunları sunucuya hiç taşımadı. Yeni epizot tablosuyla birlikte o üç
# migration da buradan uygulanır; hepsi idempotent (IF NOT EXISTS).

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

for migration in \
  drizzle/0052_learning_events_task_key_unique.sql \
  drizzle/0053_chat_message_orphan_reconcile.sql \
  drizzle/0054_task_automations.sql \
  drizzle/0055_task_episodes.sql \
  drizzle/0056_compiled_templates.sql; do
  echo "==> Applying ${migration}"
  docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    < "${migration}"
done

echo "==> Task episodes schema bootstrap complete"
