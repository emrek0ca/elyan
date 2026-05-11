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
