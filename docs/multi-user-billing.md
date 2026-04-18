# Multi-User Billing and Entitlements

This document describes the runtime billing spine used by Elyan for multi-user operation.

## Runtime model

- Ownership is scoped by `workspace_id`, `actor_id`, `session_id`, and `run_id`.
- Usage is tracked as events plus a ledger, not as a single mutable counter.
- The product surface shows credits, reset time, top cost sources, and upgrade hints.
- Billing snapshots carry trace context so usage can be attributed back to the exact request/session/run path.

## Credits and ledger

- User-facing consumption is shown as credits.
- Internal usage is calculated from tokens, tools, memory/indexing, model tier, deep mode, and queue priority.
- Ledger entry types include `grant`, `usage`, `refund`, `bonus`, `expire`, `manual_adjustment`, and reset-related grants.
- `usage_events` keeps the auditable history; `credit_ledger` keeps balance movement.

## Plans and entitlements

- Supported plan families: `free`, `trial`, `starter`, `flow`, `pro`, `operator`, `team`, `business`.
- Entitlements are enforced on the backend.
- Feature flags cover web tools, file analysis, long context, deep mode, voice, screen features, multi-agent, premium memory, and priority queue access.
- Paid plan completions are plan-scoped, so provider completion callbacks grant the correct included credits for the target plan and billing period.

## Weekly reset

- Free users receive a weekly included credit grant.
- Reset windows are anchored to the plan reset policy and are idempotent.
- Unused free credits do not roll over.
- Paid plans can carry rollover policy metadata, but v1 keeps the behavior simple.
- Legacy workspaces are normalized through deterministic backfill, which is safe to run repeatedly.

## Abuse protection

- Request-per-minute limits are enforced.
- Per-hour credit spend caps are enforced.
- Weekly hard caps are enforced where configured.
- Costly actions can return graceful degradation or a hard rejection depending on the gate.

## Admin and dev operations

- `elyan billing status` shows the current workspace billing snapshot.
- `elyan billing plans` lists the current catalog.
- `elyan billing inspect` prints recent ledger entries and billing events.
- `elyan billing grant` inserts a manual credit grant.
- `elyan billing reset-weekly` refreshes the current weekly balance safely.
- `elyan billing backfill` backfills one workspace when a workspace id is provided, or all known workspaces deterministically when it is not.
- `elyan billing seats list|assign|release` inspects and mutates workspace seat assignments for team/business operators.

## Current env/config dependencies

- `ELYAN_DATA_DIR`
- `ELYAN_RUNTIME_DB_PATH`
- `IYZICO_WEBHOOK_SECRET`
- `IYZICO_PLAN_PRO_CHECKOUT_URL`
- `IYZICO_PLAN_TEAM_CHECKOUT_URL`
- `IYZICO_TOKEN_PACK_STARTER_25K_CHECKOUT_URL`

## Next steps

- Extend the paid-plan completion path to the remaining provider callbacks if a new billing provider is added later.
- Expand team/business admin surfaces for any future invoice, payment, or seat billing detail views.
- Tighten cost attribution for any newly added tool paths by reusing the existing trace-enriched usage context.
