# Elyan Backend V1 Rollback

Canonical repo: `emrek0ca/elyan`

Use this when a backend V1 candidate fails smoke, post-deploy verification, or live routing truth.

## Code rollback

1. Stop rollout of the failing backend commit.
2. Identify the last known-good backend tag or commit.
3. Create a new `codex/<scope>-rollback` branch from that point.
4. Re-run:

```bash
npm ci
cp .env.example .env
npm run build
npm test
npm run db:generate
git diff --exit-code -- drizzle drizzle/meta
```

## Deploy rollback

1. Restore the last known-good source and compose configuration on the target host.
2. Rebuild and restart the backend services.
3. Re-run `bash scripts/probe-v1-runtime-flow.sh` with the target environment values.
4. Re-run `bash scripts/capture-v1-vps-smoke.sh` to create a fresh timestamped archive for the rollback candidate.
5. Only re-open traffic after health, auth/bootstrap, chat route, task create, runtime readiness, assigned-task truth, and realtime checks are green again.

## Contract rollback rules

- If the failure changes routing semantics, roll back the route decision before touching mobile or desktop clients.
- Do not hotfix by bypassing fail-closed runtime states or by moving private execution into the backend.

## Evidence rollback rules

- Keep the failed evidence folder; never overwrite it.
- Create a new timestamped evidence folder for the rollback candidate.
- Preserve any `commercialReadiness.billing=degraded` truth in the rollback evidence until the external dependency is actually removed.
