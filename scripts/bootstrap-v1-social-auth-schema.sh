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

echo "==> Bootstrapping social auth schema"
run_psql <<'SQL'
DO $$ BEGIN
  ALTER TYPE "public"."connection_provider" ADD VALUE IF NOT EXISTS 'apple' BEFORE 'notion';
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;
CREATE TABLE IF NOT EXISTS "auth_identities" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"provider" "connection_provider" NOT NULL,
	"provider_subject" varchar(160) NOT NULL,
	"email" varchar(320),
	"display_name" varchar(120),
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'auth_identities_user_id_users_id_fk'
      AND conrelid = 'public.auth_identities'::regclass
  ) THEN
    ALTER TABLE "auth_identities" ADD CONSTRAINT "auth_identities_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS "auth_identities_user_idx" ON "auth_identities" USING btree ("user_id");
CREATE INDEX IF NOT EXISTS "auth_identities_provider_idx" ON "auth_identities" USING btree ("provider");
CREATE UNIQUE INDEX IF NOT EXISTS "auth_identities_provider_subject_uidx" ON "auth_identities" USING btree ("provider","provider_subject");
CREATE UNIQUE INDEX IF NOT EXISTS "auth_identities_user_provider_uidx" ON "auth_identities" USING btree ("user_id","provider");
SQL

echo "==> Social auth schema bootstrap complete"
