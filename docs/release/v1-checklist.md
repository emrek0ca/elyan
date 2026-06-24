# Elyan Backend V1 Checklist

Canonical repo: `emrek0ca/elyan`

This checklist is binding for backend V1 work. Do not call backend "done" unless every gate below passes on a clean scoped branch and on the deployed host.

## Preflight

- [ ] `git remote get-url origin` resolves to `https://github.com/emrek0ca/elyan.git`
- [ ] worktree is clean on a single-purpose `codex/<scope>` branch
- [ ] no V1 backend release work is running from `main`
- [ ] `.env` is aligned with the target environment and does not point production traffic at localhost-only addresses

## Required CI Gates

- [ ] `npm ci`
- [ ] `cp .env.example .env`
- [ ] `npm run build`
- [ ] `npm test`
- [ ] `npm run db:generate && git diff --exit-code -- drizzle drizzle/meta`
- [ ] `bash scripts/probe-v1-runtime-flow.sh` on the deployed environment
- [ ] `bash scripts/capture-v1-vps-smoke.sh` archives a timestamped evidence folder under `docs/release/evidence/`

## V1 Scope Lock

- [ ] `POST /v1/chat/messages` remains the only chat message write path
- [ ] `POST /v1/tasks` remains the only mobile task create path
- [ ] routing stays centralized in `decideCommandRoute()`
- [ ] runtime register, heartbeat, session, and assigned task flow stays the desktop truth seam
- [ ] backend does not directly execute private local computer actions
- [ ] fail-closed states such as `desktop_required`, `pairing_required`, and capability mismatch remain intact

## Release Evidence

- [ ] deploy log includes build SHA, deploy time, and target host
- [ ] post-deploy probe confirms health, auth/bootstrap, chat route, task create, runtime heartbeat truth, runtime assigned-task truth, and realtime truth
- [ ] evidence archive includes a timestamped folder with raw JSON or text captures for health, auth, mobile, pairing, runtime, chat, task, and assigned-task probes
- [ ] evidence summary explicitly states `server core ready, commercial readiness externally blocked` when `commercialReadiness.billing=degraded`
- [ ] evidence summary records the host surface split:
  - Elyan listeners only
  - cohosted non-Elyan listeners audited but untouched
- [ ] external blockers stay visible and unresolved in release evidence until real secrets exist:
  - `APPLE_APP_STORE_*`
  - `GOOGLE_PLAY_*`
  - `IYZICO_*`
- [ ] rollback instructions in `docs/release/v1-rollback.md` were validated against the release candidate
- [ ] backend tag is not created before post-deploy probe is green
