# Elyan V1 VPS Core Smoke Evidence

- Timestamp (UTC): 20260606T163957Z
- Base URL: https://api.elyan.dev
- Direct backend port check: expected closed at `http://84.247.172.213:4000/healthz`
- Pairing session: `c58590de-5a34-4637-bcf9-bc5edcd43c87`
- Desktop device: `5e79c427-bcf1-411b-965a-a102abb90779`
- Runtime device: `5e79c427-bcf1-411b-965a-a102abb90779`
- Created task: `4acc78ed-5063-4a41-8ec7-4f1a3b4d7e8b`

## Verified chain

- `GET /healthz`
- `GET /readyz`
- direct `:4000` public path closed
- `POST /v1/auth/register`
- `GET /v1/auth/me`
- `POST /v1/devices/mobile/register`
- `GET /v1/mobile/bootstrap`
- `GET /v1/realtime/stream` emitted `event: ready`
- `POST /v1/pairing/sessions`
- `POST /v1/pairing/sessions/:sessionId/claim`
- `GET /v1/pairing/sessions/:sessionId`
- `POST /v1/runtime/register`
- `POST /v1/runtime/heartbeat`
- `GET /v1/runtime/session`
- `POST /v1/chat/messages`
- `POST /v1/tasks`
- `GET /v1/runtime/tasks/assigned`

## External blockers kept explicit

- `APPLE_APP_STORE_*`
- `GOOGLE_PLAY_*`
- `IYZICO_*`

## Host surface audit

- Elyan listeners:
  - `https://api.elyan.dev` via nginx on `:80/:443`
  - backend bound only on `127.0.0.1:4000`
  - Ollama bound only on `172.17.0.1:11434` for docker bridge access
  - `mosh` preserved on UDP `60001`
- Cohosted non-Elyan listeners audited but untouched:
  - PocketBase on `*:8090` and `127.0.0.1:8091`
  - external Node app on `*:3001`
- UFW still contains broader historical allow rules for cohosted services; Elyan-specific work in this pass did not widen them.

Server core smoke is green. Commercial readiness remains externally blocked.
