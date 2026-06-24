# Elyan Backend

Thin Fastify control-plane for Elyan's mobile -> backend -> desktop runtime flow.

## Scope

- Server-side account/session/subscription truth
- Mobile to desktop pairing and task relay
- Desktop runtime registration, heartbeat, and delivery
- Deterministic task/realtime state back to mobile

Out of scope for this backend:

- private local tool execution
- private local file or desktop context ingestion by default
- browser/computer automation execution
- skill or automation execution UX

Those surfaces belong to the desktop product and local runtime UX.

This backend can now hold Elyan brain metadata for chat orchestration without taking over local execution:

- dataset manifests and training job metadata
- model artifact registry for shared or user-scoped brain releases
- shared knowledge documents and lexical retrieval fallback
- privacy-safe learning signals and personalization hints
- Elyan brain readiness truth for mobile and desktop clients

Important:

- This repo may contain broader experimental or desktop-owned modules, but only the routes mounted in `src/app/build-app.ts` are part of the published backend contract.
- AI provider setup, MCP configuration, skills, and local execution are desktop-owned concerns and should not be treated as mobile/backend API dependencies.

## Stack

- Node.js + TypeScript
- Fastify
- PostgreSQL
- Drizzle ORM
- Zod
- WebSocket + SSE

## Structure

- `src/app`: app bootstrap and route composition
- `src/config`: env parsing and runtime configuration
- `src/contracts`: shared enums and DTO primitives
- `src/db`: Drizzle schema
- `src/lib`: auth, validation, and error helpers
- `src/modules/auth`: user auth and session management
- `src/modules/pairing`: QR pairing flow
- `src/modules/runtime`: desktop runtime registration and heartbeat
- `src/modules/tasks`: task lifecycle and artifact contracts
- `src/modules/realtime`: SSE/WebSocket delivery
- `src/modules/health`: liveness/readiness

## Quick start

1. Copy `.env.example` to `.env`
2. Set `APP_BASE_URL` to the backend machine LAN IP or public host before any phone or another developer machine connects
3. Start the shared backend stack with `docker compose up --build`
4. Push schema with `npm run db:push`

`docker compose up --build` is the recommended path for desktop/mobile developers because it boots both the backend and PostgreSQL with a deterministic `DATABASE_URL`. The backend container talks to Postgres through the internal `postgres` hostname, so contributors do not need a machine-specific local database user just to reach the API.

If you want to run the backend directly on the host instead:

1. Keep PostgreSQL running on `127.0.0.1:5432`
2. Install deps with `npm install`
3. Push schema with `npm run db:push`
4. Start the dev server with `npm run dev`

For physical phones or another developer machine, set `APP_BASE_URL` to the backend machine's LAN IP or public host. `127.0.0.1` only works on the same machine that runs the backend.

## Notes

- Real execution stays on the desktop runtime
- Account and subscription truth stays on the server
- This backend intentionally stays thin and deterministic
- Drizzle migration generation reads the compiled `dist/db/schema.js` to stay compatible with the NodeNext import layout
- Mobile/frontend integration flow is documented in `docs/mobile-frontend-integration.md`
- Desktop runtime ownership and provider/MCP boundary is documented in `docs/desktop-runtime-handoff.md`
- `/healthz` now reports the advertised backend origin so reachability mistakes show up immediately
- `x-request-id` is returned on every response so retries, logs, and support traces can be correlated quickly

## API Surfaces

- `GET /healthz`, `GET /livez`, `GET /readyz`
- `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/refresh`, `GET /v1/auth/me`
- `POST /v1/pairing/sessions`, `GET /v1/pairing/sessions/:sessionId`, `POST /v1/pairing/sessions/:sessionId/claim`
- `POST /v1/runtime/register`, `POST /v1/runtime/heartbeat`, `POST /v1/runtime/disconnect`, `GET /v1/runtime/session`, `GET /v1/runtime/tasks/assigned`
- `GET /v1/realtime/stream`, `GET /v1/realtime/runtime` (websocket)
- `POST /v1/tasks`, `GET /v1/tasks`, `GET /v1/tasks/:taskId`, `POST /v1/tasks/:taskId/cancel`, `POST /v1/tasks/:taskId/approval`
- `GET /v1/devices`, `POST /v1/devices/mobile/register`, `GET /v1/devices/:deviceId/backlog`
- `GET /v1/mobile/bootstrap`
- `GET /v1/billing/plans`, `GET /v1/billing/summary`
- `GET /v1/billing/profile`, `PUT /v1/billing/profile`
- `POST /v1/billing/checkout/init`, `GET /v1/billing/checkouts/:referenceId`, `GET /v1/billing/checkouts/:referenceId/launch`
- `POST /v1/billing/store/verify`
- `GET|POST /v1/billing/callbacks/iyzico`, `POST /v1/billing/webhooks/iyzico`, `POST /v1/billing/webhooks/apple`, `POST /v1/billing/webhooks/google`
- `POST /v1/billing/subscription/change-plan`, `POST /v1/billing/subscription/cancel`
- `GET /v1/brain/profile`
- `GET|POST|PUT /v1/brain/datasets`
- `GET|POST /v1/brain/training-jobs`, `POST /v1/brain/training-jobs/:jobId/cancel`
- `GET|POST|PUT /v1/brain/models`
- `POST /v1/brain/knowledge/documents`, `POST /v1/brain/retrieval/search`
- `GET|POST /v1/chat/sessions`, `GET /v1/chat/sessions/:sessionId`
- `POST /v1/chat/messages`
- `GET /train`

Mobile and desktop user surfaces should read daily and weekly trial quota truth from `usage.dailyLimit`, `usage.dailyUsed`, `usage.dailyRemaining`, `usage.dailyResetAt`, `usage.dailyProgressPercent`, `usage.weeklyLimit`, `usage.weeklyUsed`, `usage.weeklyRemaining`, `usage.weeklyResetAt`, and `usage.weeklyProgressPercent` on `GET /v1/auth/me` and `GET /v1/mobile/bootstrap`.
Payment provider code remains in the backend, but the active mobile/desktop experience is quota-first until billing is re-opened.

`GET /v1/brain/profile` now publishes the shared brain control-plane truth used by mobile and desktop:

- `sections.runtime`
- `sections.model`
- `sections.routing`
- `sections.learning`
- `chat.inferenceReady`
- `chat.servingProvider`
- `chat.baseModel`
- `chat.activeAdapter`
- `chat.warmupJobId`
- `training.pipeline.promotion`
- `training.pipeline.runtimeReady`

The backend warms the Elyan runtime on boot and will fall back from the primary provider to the configured fallback provider when the primary target is unhealthy.
Desktop runtime registrations now also carry a normalized capability set and `runtime_capability_mismatch` is returned when a task asks for capabilities the selected desktop does not have.

Detailed handoff notes live in:

- `docs/mobile-elyan-handoff.md`
- `docs/desktop-elyan-handoff.md`

## Reliability Notes

- Use `Idempotency-Key` on `POST /v1/tasks` and `POST /v1/billing/checkout/init` retries
- Mobile chat/task clients must use only `POST /v1/chat/messages` and `GET /v1/realtime/stream`; model servers and desktop runtime control channels stay backend/private.
- `GET /v1/realtime/stream` persists events to PostgreSQL for `Last-Event-ID` replay and uses Redis fanout when `REALTIME_REDIS_FANOUT_ENABLED=true`, so multiple backend instances can deliver the same lifecycle stream.
- Realtime event retention is intentionally short (`REALTIME_EVENT_RETENTION_HOURS`, default 48h). Older chat/task state should hydrate from canonical history tables, not from the SSE event log.
- `POST /v1/devices/mobile/register` is naturally idempotent by `(userId, type, externalDeviceId)`
- Runtime auth tokens are bound to a specific runtime connection; a replaced desktop runtime cannot continue mutating task state with a stale token
- `POST /v1/runtime/register` does not make a desktop ready by itself; backend truth becomes ready only after websocket connect or a fallback `POST /v1/runtime/heartbeat`
- Desktop target readiness is fail-closed: mobile should treat `isOnline && canReceiveTasks` as the only ready signal, and `canReceiveTasks` stays false when `/healthz.network.externalClientsCanReachAdvertisedBaseUrl !== true`
