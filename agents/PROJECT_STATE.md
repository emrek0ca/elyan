# PROJECT_STATE

Last updated: 2026-04-29

## Read First In Every Codex Session
- Read this file before planning or editing.
- Treat `agents/` as Codex/development workflow metadata only.
- Do not add user-facing Elyan CLI/API/UI behavior for `agents/` workflow metadata.
- Confirm the target surface before changing files: local runtime, desktop UI, `elyan-dev`, `apps/web`, VPS/control-plane, docs, or workflow metadata.
- Keep context tight: read only what the task needs, then update this file after meaningful work.

## Elyan Product Model
- Elyan is a local-first personal operator runtime.
- The local runtime is the real agent system and keeps private local context on the user's machine by default.
- Hosted surfaces support account, billing, subscription, device, usage, notification, and release state.
- Development workflow metadata in `agents/` is not an Elyan product feature.

## Surface Boundaries
- Local runtime: `core/`, `cli/`, `config/`, local SQLite/runtime state, skills, routines, memory, gateway, and execution policy.
- Desktop app: `apps/desktop/`, local UI for runtime status, onboarding, auth hydration, task execution, integrations, and settings.
- `elyan-dev/`: public/static website and static panel surface; it exports `out/` and must not define backend truth.
- `apps/web/`: hosted web/control-plane workspace when explicitly targeted; owns hosted account/control-plane behavior.
- VPS/control-plane: shared truth for auth, billing, subscription, token ledger, notifications, device sync, and release metadata.
- Private local memory/context must not be moved to VPS/control-plane unless a future explicit product flow defines consent, scope, and tests.

## Current Deploy Model
- `elyan-dev/next.config.ts` uses static export with trailing slash and unoptimized images.
- `elyan-dev/out/` is generated deploy output for static hosting such as Hostinger `public_html`.
- VPS/API deploy is separate from `elyan-dev` static deploy.
- README states the live VPS surface uses `/srv/elyan`, `/srv/elyan/current`, systemd service `elyan`, bind `127.0.0.1:3010`, and public domain `api.elyan.dev`.
- GitHub Releases plus VPS API are release metadata truth.

## Important Directories
- `agents/`: Codex/development workflow metadata and session state.
- `core/`: runtime, gateway, persistence, agents, memory, scheduler, policy, and execution internals.
- `cli/`: user-facing Elyan CLI commands; do not add workflow-metadata commands here.
- `config/`: runtime configuration.
- `apps/desktop/`: local desktop app.
- `apps/web/`: hosted web/control-plane workspace.
- `elyan-dev/`: public/static website and panel surface.
- `.elyan/`: local runtime-adjacent data, approvals, runs, memory, and state; do not treat as source code.

## Important Env Surfaces
- Root `.env` and `.env.example`: local runtime/gateway configuration examples and local setup values.
- `elyan-dev/.env.local`: static hosted frontend variables.
- `apps/web` env: hosted control-plane variables such as `DATABASE_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, and billing provider keys.
- VPS env files: production API/control-plane secrets and service config; never expose values in docs or logs.
- Provider/channel env keys such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are sensitive.

## Recent Decisions
- `agents/` is development workflow metadata only.
- Do not wire `agents/PROJECT_STATE.md` into Elyan runtime, CLI, hosted web, or product UI.
- `agents project` was rejected as product CLI pollution and should not be reintroduced.
- `apps/web` and `elyan-dev/` are separate surfaces: hosted control-plane vs static/public frontend.
- Large work must follow Orchestrator -> Memory/Context -> Planner -> Builder/UI -> Reviewer -> Release/Ops if needed -> Memory/Context.
- Use installed/awesome-codex skills only when they improve the task.

## Active Blockers
- No active code blocker for the workflow metadata setup.
- Main process risk: accidentally mixing development metadata with product code.
- Main architecture risk: boundary drift between local runtime, hosted control-plane, and static/public frontend.
- Generated output such as `.next/`, `out/`, caches, local DBs, and `.elyan/` runtime state must not be treated as source.

## Last Completed Work
- Created durable agent instruction files for Orchestrator, Planner, UI, Builder, Reviewer, Release/Ops, and Memory/Context.
- Added `agents/README.md` as the routing reference.
- Reverted the product-facing `agents project` CLI surface; `agents/` remains workflow metadata only.
- Refined agent contracts with ownership boundaries, model classes, skill rules, output formats, and review checklists.

## Next Recommended Step
- Use this workflow for the next real development task without adding product-facing metadata commands.
- Start Phase 1 with local runtime/desktop stability only after Orchestrator classifies the exact surface and Planner writes acceptance criteria.
- After each meaningful task, Memory/Context should update this file with decisions, blockers, and next step.

