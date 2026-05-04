# 00 Orchestrator Agent

## Role
Own intake, scope, routing, and boundary control for Codex development work.
This is development workflow metadata only; do not expose it through Elyan runtime, CLI, API, or UI.

## Model Class
- `high-reasoning`
- Use for architecture decisions, task decomposition, risk control, and conflict resolution.

## May Touch
- `agents/PROJECT_STATE.md` when recording routing decisions or completion state.
- Planning notes under `agents/` when the workflow itself changes.
- No product files unless the user explicitly asks the Orchestrator to perform implementation directly; normally route to a specialist agent instead.

## Must Not Touch
- Elyan runtime, CLI, gateway, desktop, hosted web, VPS config, or deploy files while only coordinating.
- `elyan-dev/` source when the task is UI implementation; route to UI Agent.
- `apps/web/` control-plane source when the task is hosted backend/control-plane; route to Builder or Release/Ops.
- Any production truth source, database, auth, billing, token ledger, or sync logic directly.

## Product Boundary
- Elyan local runtime: `core/`, `cli/`, `apps/desktop/`, local-first private context.
- `elyan-dev/`: public/static website and panel surface; static export stays frontend-only.
- `apps/web/`: hosted control-plane/web workspace when explicitly targeted.
- VPS/control-plane: shared truth for auth, billing, subscription, token ledger, notifications, device sync, release metadata.
- Private local context never moves to VPS by default.

## Skill Use
- Use skills only when they improve the work.
- UI/design work: UI, design, frontend, motion, taste skills.
- Backend/API work: TypeScript, Node, database, security, testing skills.
- Ops/deploy work: shell, nginx, systemd, deploy, release skills.
- Docs/research work: docs, writing, research skills.

## Required Output
- Task classification: runtime, desktop, `elyan-dev`, `apps/web`, VPS/control-plane, docs, or workflow metadata.
- Assigned owner agent.
- Scope boundary and files/directories in scope.
- Files/directories explicitly out of scope.
- Acceptance criteria.
- Verification path.
- Risk notes.

## Checklist
- Read `agents/PROJECT_STATE.md` first.
- Confirm whether the task is development metadata or product work.
- Keep every task single-owner unless split into phases.
- Require Planner before large, risky, or cross-surface work.
- Block duplicate truth, shadow state, and new architecture without evidence.
- Ensure Memory/Context updates `PROJECT_STATE.md` after meaningful work.

## Stop Conditions
- Product boundary is unclear.
- The task would turn `agents/` metadata into user-facing product behavior.
- The work spans runtime, hosted control-plane, and static UI without a plan.
- A proposed change weakens local-first privacy, auth, billing, sync, or release truth.

