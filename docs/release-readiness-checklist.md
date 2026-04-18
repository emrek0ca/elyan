# Release Readiness Checklist

This checklist defines readiness gates for serious private beta.

## 1) Must-Have Before Private Beta

### A) Onboarding and Auth
- [ ] `bootstrap-owner -> login -> auth/me -> logout` flow works on localhost end-to-end.
- [ ] `/healthz` reflects real readiness (`setup_complete`, provider/channel/routine state).
- [ ] Desktop route guard behavior is consistent (`onboarding`, `login`, `home`).

### B) Model and Runtime Setup
- [ ] At least one model lane is runnable (local or cloud configured).
- [ ] Provider status in `/api/v1/system/overview` matches actual connectivity.
- [ ] Runtime start/stop is stable via CLI and desktop sidecar health checks.

### C) Skills / Routines / Draft Review
- [ ] `/api/skills` and `/api/skills/workflows` return usable stack state.
- [ ] `/api/routines` lifecycle works (create/toggle/run/history/delete).
- [ ] `/api/learning/drafts` lists drafts reliably.
- [ ] `/api/skills/from-draft` and `/api/routines/from-draft` promote correctly.

### D) Task Execution Safety
- [ ] Approval/security paths do not bypass loopback/session checks.
- [ ] Run state is persisted and queryable (`run_store` + runtime DB run index).
- [ ] Errors are surfaced as explicit API responses, not hidden.

### E) Desktop UX Baseline
- [ ] Home and onboarding show true runtime status, not placeholders.
- [ ] Blocking states (auth failure, provider failure, no model, no channel) are understandable.
- [ ] Learned draft queue state is visible and actionable.

### F) Security and Privacy
- [ ] Session/cookie/CSRF behavior validated on protected endpoints.
- [ ] Websocket auth requires explicit auth message token.
- [ ] Upload endpoints enforce MIME, size, and safe file paths.
- [ ] Webhook signature validation path remains active.
- [ ] Privacy endpoints (`/api/v1/privacy/*`) return consistent data.

### G) Multi-User Readiness Baseline
- [ ] Workspace isolation checks block cross-workspace run/thread access.
- [ ] Workspace role and seat logic works for owner/member flows.
- [ ] No endpoint silently falls back to wrong workspace in authenticated flows.

## 2) Should-Have After Beta Start
- [ ] Reduce legacy surface duplication (gateway/runtime adapters).
- [ ] Improve routine persistence/observability beyond single JSON file.
- [ ] Harden draft quality controls (confidence thresholds + review UX).
- [ ] Expand integration tests for auth + connector + billing combined paths.
- [ ] Improve structured error taxonomy and front-end mapping.

## 3) Later Strategic Improvements
- [ ] Unified multi-tenant SaaS mode without local-single-user assumptions.
- [ ] Decision fabric and pattern/ambient intelligence promoted from partial to production path.
- [ ] Consolidate duplicated runtime modules into one authoritative execution architecture.
- [ ] Formal API versioning policy and migration docs.

## 4) Current Known Blockers to Track Closely
- Legacy/parallel module surfaces can confuse contributors and increase drift.
- Local-first defaults still dominate; multi-user posture is partially implemented.
- Routine state is file-backed; operational consistency under heavier concurrency needs validation.
- Some `core/runtime/*` modules appear incomplete/legacy relative to production gateway path.

## 5) Release Sign-Off Evidence
For each release candidate, record:
1. Commands run and timestamps.
2. Endpoint checks and sample responses.
3. Targeted test suites executed.
4. Known open risks accepted by owner.
