# Desktop Runtime Handoff

Desktop owns real execution. This backend does not own provider setup, MCP setup, skills, or local automation UX.

Backend may now expose Elyan brain metadata for chat orchestration:

- shared or user-scoped model artifact registry
- dataset and training job metadata
- shared knowledge documents and retrieval search

That does not move private local execution into the backend.

## What desktop should keep local

- AI provider credentials, model routing preferences, and provider failover logic
- MCP server setup, discovery, and tool wiring
- skill and automation configuration
- browser, filesystem, app control, and artifact generation

Do not build a new orchestrator from scratch. Update the existing desktop/runtime surfaces and keep backend integration thin.

## Backend contract desktop should use

- `POST /v1/pairing/sessions`
- `GET /v1/pairing/sessions/:sessionId`
- `POST /v1/pairing/sessions/:sessionId/claim`
- `POST /v1/runtime/register`
- `POST /v1/runtime/heartbeat`
- `POST /v1/runtime/disconnect`
- `GET /v1/runtime/session`
- `GET /v1/runtime/tasks/assigned`
- `POST /v1/runtime/tasks/:taskId/status`
- `POST /v1/runtime/tasks/:taskId/artifacts`
- `GET /v1/realtime/runtime` websocket

## Runtime rules

- Treat backend as account, billing, device, pairing, task relay, and realtime truth only
- Keep provider and MCP state in desktop-owned secure storage
- Runtime tokens are connection-bound; after a replacement register, stale runtime tokens must be discarded
- Desktop pairing and runtime registration are Pro-only. Solo users may still chat and send tasks through the backend, but they must not see or use desktop runtime connect flows.
- Safe user-facing failure codes for plan gating are `desktop_plan_required` and `desktop_limit_reached`; do not surface raw backend exceptions.
- `POST /v1/runtime/register` alone does not make the desktop ready; backend truth becomes ready only after websocket connect or a fallback `POST /v1/runtime/heartbeat`
- Use the runtime access token only for runtime endpoints and websocket auth; never mix it with user tokens
- On reconnect or restart, always do a fresh register; backend will invalidate and close the previous runtime connection
- `GET /v1/runtime/session` now includes `readiness.isOnline`, `readiness.canReceiveTasks`, `readiness.targetStatus`, and `readiness.targetErrorCode`
- When reconnecting, recover active work from `GET /v1/runtime/session` or the runtime websocket dispatch stream instead of inventing a second queue
- If `/healthz.network.externalClientsCanReachAdvertisedBaseUrl !== true`, treat the backend as not ready for cross-device pairing or task delivery even if the local runtime is up

## What not to depend on

- Do not assume repo-internal `ai`, `integrations`, `mcp`, or similar modules are published backend APIs
- Do not move provider or MCP management into mobile or public backend surfaces unless the contract is explicitly expanded later

## Frontend note

- Desktop UI should only render pairing / connect controls after reading backend truth that the account is Pro
- Use the backend `planCode` and `readiness.targetStatus` fields as the source of truth for connect buttons, banners, and status pills
- If the backend says `plan_restricted`, the desktop shell should show an upgrade/plan explanation instead of retrying connect
- Do not hardcode plan names or availability in the shell; keep the UI driven by backend truth so Solo and Pro stay in sync
