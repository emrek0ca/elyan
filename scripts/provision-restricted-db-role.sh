#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.server.yaml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-elyan_backend}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD is required}"
: "${POSTGRES_WORKER_PASSWORD:?POSTGRES_WORKER_PASSWORD is required}"

docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  psql -v ON_ERROR_STOP=1 -v app_password="${POSTGRES_APP_PASSWORD}" \
  -v worker_password="${POSTGRES_WORKER_PASSWORD}" \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<'SQL'
SELECT format(
  'CREATE ROLE elyan_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elyan_app')
\gexec

SELECT format('ALTER ROLE elyan_app PASSWORD %L', :'app_password')
\gexec

SELECT 'CREATE ROLE elyan_brain_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elyan_brain_worker')
\gexec

SELECT format(
  'CREATE ROLE elyan_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
  :'worker_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elyan_worker')
\gexec

SELECT format('ALTER ROLE elyan_worker PASSWORD %L', :'worker_password')
\gexec

GRANT elyan_brain_worker TO elyan_worker;

SELECT format('GRANT CONNECT ON DATABASE %I TO elyan_app', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO elyan_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO elyan_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO elyan_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO elyan_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO elyan_app;

SELECT format('GRANT CONNECT ON DATABASE %I TO elyan_worker', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO elyan_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO elyan_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO elyan_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO elyan_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO elyan_worker;
SQL

echo "Restricted role provisioned. Set DATABASE_APP_URL with the elyan_app credentials before enabling RLS."
