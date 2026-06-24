# Elyan Backend V1 Smoke Runbook

Canonical repo: `emrek0ca/elyan`

Run this after CI is green and after every production deploy candidate.

## 1. Clean verification

```bash
npm ci
cp .env.example .env
npm run build
npm test
npm run db:generate
git diff --exit-code -- drizzle drizzle/meta
```

## 2. Deploy candidate

Use the helper when targeting the VPS:

```bash
bash scripts/deploy-v1-release.sh
```

## 3. Post-deploy probe

Run the probe with real auth/runtime values for the target environment:

```bash
BASE_URL=https://api.elyan.dev \
AUTH_BEARER_TOKEN=... \
DESKTOP_DEVICE_ID=... \
RUNTIME_BEARER_TOKEN=... \
bash scripts/probe-v1-runtime-flow.sh
```

The probe assumes the current API contract:

- `POST /v1/chat/messages` receives `source`, `content`, `requestedCapabilities`, and optional `targetDeviceId`
- `POST /v1/tasks` receives `title`, `payload`, `requestedCapabilities`, and optional `targetDeviceId`
- invalid Google and Apple OAuth tokens must fail cleanly with a 400/401-class response, never a 500

## 4. Required V1 flow checks

1. Public chat path:
   - `POST /v1/chat/messages`
   - confirm a shared-brain response returns without creating a desktop-required task
2. Desktop-required path:
   - `POST /v1/tasks`
   - confirm routing selects the paired desktop and task lifecycle events stream correctly
3. Pairing-required path:
   - remove the ready desktop or target a user without a paired desktop
   - confirm the backend fails closed
4. Risky approval path:
   - confirm backend relays the waiting-approval state and the approval resume event
5. Failed-safe path:
   - break runtime readiness or capability match
   - confirm backend returns the correct safe error instead of silent fallback

## 5. No-secret evidence capture

Use the timestamped capture helper to generate a release archive without keeping live tokens in git:

```bash
BASE_URL=https://api.elyan.dev \
DIRECT_HEALTHCHECK_URL=http://84.247.172.213:4000/healthz \
bash scripts/capture-v1-vps-smoke.sh
```

Expected archive root:

- `docs/release/evidence/<UTC-stamp>-vps-core-smoke/`

Required contents:

- `healthz.json`
- `readyz.json`
- `auth-register.json`
- `auth-me.json`
- `mobile-register.json`
- `mobile-bootstrap.json`
- `realtime-stream.txt`
- `pairing-create.json`
- `pairing-claim.json`
- `pairing-status.json`
- `runtime-register.json`
- `runtime-heartbeat.json`
- `runtime-session.json`
- `chat-message.json`
- `task-create.json`
- `runtime-tasks-assigned.json`
- `SUMMARY.md`

## 6. Evidence capture rules

- archive the probe output
- archive the deployed commit SHA and tag candidate
- archive one recorded realtime/task lifecycle session for the release note
- keep `commercialReadiness.billing=degraded` visible when Apple, Google Play, or Iyzico secrets are missing
- write the blocker list explicitly in `SUMMARY.md`:
  - `APPLE_APP_STORE_*`
  - `GOOGLE_PLAY_*`
  - `IYZICO_*`
