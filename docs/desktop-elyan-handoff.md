# Elyan Desktop Handoff

Desktop remains the private runtime. It owns real execution, local tools, MCP wiring, and provider setup.

## What changed on the backend

- Elyan's main brain is now treated as the backend-owned serving target for chat fallback and orchestration truth.
- The backend now exposes readiness state in `GET /v1/brain/profile`.
- Routing policy stays centralized in the backend.
- Task and token allowance is counted server-side only.
- Desktop no longer needs to maintain its own token counter.

## What desktop should read

Use these endpoints as the backend truth surfaces:

- `GET /v1/auth/me`
- `GET /v1/mobile/bootstrap`
- `GET /v1/brain/profile`
- `GET /v1/runtime/session`
- `GET /v1/runtime/tasks/assigned`

### Brain readiness

Use these fields from `GET /v1/brain/profile`:

- `brain.sections.runtime`
- `brain.sections.model`
- `brain.sections.routing`
- `brain.sections.learning`
- `brain.chat.inferenceReady`
- `brain.chat.servingProvider`
- `brain.chat.baseModel`
- `brain.chat.activeAdapter`
- `brain.chat.warmupJobId`
- `brain.chat.serverBrainName`
- `brain.training.pipeline.runtimeReady`
- `brain.training.pipeline.promotion`

`brain.chat.serverBrainName` is `Elyan`. That is the user-visible name for the main model.

### Runtime readiness

Use `GET /v1/runtime/session.readiness` for desktop availability:

- `isOnline`
- `canReceiveTasks`
- `targetStatus`
- `targetErrorCode`
- `runtime.capabilitySummary`

Desktop should treat `canReceiveTasks` as the final readiness gate for accepting tasks.

## Connection flow

1. Register the runtime with `POST /v1/runtime/register`.
2. Open the websocket at `GET /v1/realtime/runtime`.
3. Continue heartbeats through `POST /v1/runtime/heartbeat`.
4. Pull assigned work from `GET /v1/runtime/tasks/assigned`.
5. Update task status through `POST /v1/runtime/tasks/:taskId/status`.
6. Send artifacts through `POST /v1/runtime/tasks/:taskId/artifacts`.

Do not add a second queue or a second routing decision in the desktop app.

## Task routing behavior

- If desktop is online and ready, backend should route tasks to desktop.
- If desktop is offline, backend may fall back to Elyan for chat-facing work.
- Desktop should never increment token usage.
- Desktop should never guess token remaining from its own local state.

## UI rules

- Do not show billing, plan, or upsell surfaces.
- Do not expose internal provider hostnames or base URLs.
- Do not block the UI on model warmup details.
- Treat `server_brain_unavailable` as a backend state, not a desktop routing state.

## Error mapping

Map backend codes to short messages:

- `daily_quota_reached` -> `Günlük token hakkı doldu.`
- `weekly_quota_reached` -> `Haftalık token hakkı doldu.`
- `device_offline` -> `Masaüstü çevrimdışı.`
- `runtime_unreachable` -> `Backend erişimi yok.`
- `task_runtime_owner_conflict` -> `Bu görev başka bir oturumda açık.`
- `runtime_capability_mismatch` -> `Bu görev için uygun capability yok.`
- `server_brain_unavailable` -> `Elyan şu anda yanıt veremiyor.`

## Important boundary

Desktop owns local execution and provider setup.
Backend owns identity, routing truth, token allowance, brain readiness, and training promotion truth.
Keep those responsibilities separate.
