#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:-/srv/elyan-backend}"
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

cd "${REMOTE_DIR}"

echo "==> Ensuring PostgreSQL is up"
docker compose -f "${COMPOSE_FILE}" up -d "${POSTGRES_SERVICE}"
wait_for_postgres

echo "==> Bootstrapping operator runtime schema"
docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<'SQL'
CREATE TABLE IF NOT EXISTS "operator_runs" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "public"."users"("id") ON DELETE cascade,
  "device_id" uuid NOT NULL REFERENCES "public"."devices"("id") ON DELETE cascade,
  "task_id" uuid REFERENCES "public"."tasks"("id") ON DELETE set null,
  "run_key" varchar(120) NOT NULL,
  "task" text NOT NULL,
  "status" varchar(40) DEFAULT 'running' NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS "screen_observations" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "operator_run_id" uuid REFERENCES "public"."operator_runs"("id") ON DELETE cascade,
  "screenshot_hash" varchar(128) NOT NULL,
  "elements_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "active_app" varchar(255),
  "active_window" varchar(500),
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS "operator_steps" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "operator_run_id" uuid NOT NULL REFERENCES "public"."operator_runs"("id") ON DELETE cascade,
  "step_index" integer NOT NULL,
  "screen_observation_id" uuid REFERENCES "public"."screen_observations"("id") ON DELETE set null,
  "proposed_action" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "executed_action" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "result" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "requires_approval" boolean DEFAULT false NOT NULL,
  "approved_by_user" boolean DEFAULT false NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS "input_actions" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "operator_step_id" uuid NOT NULL REFERENCES "public"."operator_steps"("id") ON DELETE cascade,
  "action_type" varchar(64) NOT NULL,
  "target_bbox" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "text_redacted" boolean DEFAULT false NOT NULL,
  "status" varchar(40) DEFAULT 'pending' NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "operator_runs_user_idx" ON "operator_runs" ("user_id");
CREATE INDEX IF NOT EXISTS "operator_runs_device_idx" ON "operator_runs" ("device_id");
CREATE INDEX IF NOT EXISTS "operator_runs_task_idx" ON "operator_runs" ("task_id");
CREATE UNIQUE INDEX IF NOT EXISTS "operator_runs_run_key_uidx" ON "operator_runs" ("run_key");
CREATE INDEX IF NOT EXISTS "screen_observations_run_idx" ON "screen_observations" ("operator_run_id");
CREATE INDEX IF NOT EXISTS "screen_observations_hash_idx" ON "screen_observations" ("screenshot_hash");
CREATE UNIQUE INDEX IF NOT EXISTS "operator_steps_run_step_uidx" ON "operator_steps" ("operator_run_id", "step_index");
CREATE INDEX IF NOT EXISTS "input_actions_step_idx" ON "input_actions" ("operator_step_id");
SQL

echo "==> Operator runtime schema bootstrap complete"
