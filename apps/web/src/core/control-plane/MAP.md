# Control-Plane Map

## Auth Flow

`POST /api/control-plane/auth/register` creates the hosted account in PostgreSQL.
`POST /api/auth/callback/credentials` validates the password and creates the NextAuth session cookie.
`GET /api/control-plane/auth/me` reads the authenticated session and resolves the hosted profile.
`GET /api/control-plane/panel` resolves the same session plus account/device/billing state for the panel.

## Request Flow

Frontend or local probes call the route handler.
The route handler delegates to `src/core/control-plane/*`.
The service layer reads or writes PostgreSQL through `database.ts`, `postgres-store.ts`, and `migrations.ts`.

## Responsibility Boundaries

- `auth.ts`, `session.ts`: auth/session wiring and guards.
- `database.ts`, `migrations.ts`: PostgreSQL connection, schema, and migration verification.
- `service.ts`: hosted control-plane domain logic.
- `status.ts`: readiness and diagnostic snapshots only.
- `response.ts`, `display.ts`: response shaping and presentation helpers.

## Entrypoints

- `src/app/api/auth/[...nextauth]/route.ts`
- `src/app/api/control-plane/auth/register/route.ts`
- `src/app/api/control-plane/auth/me/route.ts`
- `src/app/api/control-plane/panel/route.ts`
- `src/app/api/control-plane/health/route.ts`
- `src/app/api/healthz/route.ts`
