# Elyan Backend

Thin Fastify control-plane for Elyan's mobile -> backend -> desktop runtime flow.

## Scope

- Mobile submits tasks
- Backend authenticates user and device
- Backend pairs mobile with desktop runtime
- Backend queues and routes tasks
- Desktop runtime performs real execution
- Backend streams deterministic status and artifacts back to mobile

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
- `src/modules/ai`: supported provider registry

## Quick start

1. Copy `.env.example` to `.env`
2. Start PostgreSQL
3. Install deps with `npm install`
4. Push schema with `npm run db:push`
5. Start dev server with `npm run dev`

## Notes

- Real execution stays on the desktop runtime
- AI providers are advisory only
- This backend intentionally stays thin and deterministic
- Drizzle migration generation reads the compiled `dist/db/schema.js` to stay compatible with the NodeNext import layout

## API Surfaces

- `GET /healthz`, `GET /livez`, `GET /readyz`
- `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/refresh`, `GET /v1/auth/me`
- `POST /v1/pairing/sessions`, `GET /v1/pairing/sessions/:sessionId`, `POST /v1/pairing/sessions/:sessionId/claim`
- `POST /v1/runtime/register`, `POST /v1/runtime/heartbeat`, `GET /v1/runtime/session`, `GET /v1/runtime/tasks/assigned`
- `GET /v1/realtime/stream`, `GET /v1/realtime/runtime` (websocket)
- `POST /v1/tasks`, `GET /v1/tasks`, `GET /v1/tasks/:taskId`, `POST /v1/tasks/:taskId/cancel`, `POST /v1/tasks/:taskId/approval`
- `GET /v1/devices`, `POST /v1/devices/mobile/register`, `GET /v1/devices/:deviceId/backlog`
- `GET /v1/mobile/bootstrap`
- `GET /v1/ai/providers`, `PUT /v1/ai/credentials/:provider`, `POST /v1/ai/route-preview`, `GET /v1/ai/usage`
- `GET /v1/integrations/providers`, `GET /v1/integrations/connections`, `POST /v1/integrations/oauth/:provider/start`, `GET /v1/integrations/oauth/:provider/callback`
- `GET /v1/mcp/servers`, `POST /v1/mcp/servers`, `PATCH /v1/mcp/servers/:serverId`
- `GET /v1/security/audit-logs`
