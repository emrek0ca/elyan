# Agents README

This folder is Codex/development workflow metadata for Elyan.
It is not an Elyan product feature and must not be wired into runtime, CLI, API, hosted web, or desktop UI.

## Surface Map

- Elyan local runtime: `core/`, `cli/`, `config/`, local-first memory, execution, gateway, routines, skills.
- Desktop app: `apps/desktop/`, local runtime UI and operator shell.
- `elyan-dev/`: public/static website and static panel surface; keeps static export.
- `apps/web/`: hosted web/control-plane workspace when explicitly targeted.
- VPS/control-plane: shared truth for auth, billing, subscription, token ledger, notifications, device sync, release metadata.

## Workflow

1. Orchestrator reads the request and `PROJECT_STATE.md`.
2. Memory/Context summarizes current state when needed.
3. Planner writes the plan and acceptance criteria.
4. UI or Builder implements the approved scope.
5. Reviewer checks bugs, security, regression, and boundaries.
6. Release/Ops handles deploy only if needed.
7. Memory/Context updates `PROJECT_STATE.md`.

## Agent Routing

- `00-orchestrator.md`: intake, routing, boundary control.
- `01-planner-agent.md`: plans, file impact, acceptance criteria.
- `02-ui-agent.md`: UI/UX, frontend polish, motion, layout.
- `03-builder-agent.md`: implementation, tests, debugging.
- `04-reviewer-agent.md`: review, security, regression, architecture boundaries.
- `05-release-ops-agent.md`: deploy, VPS, systemd, nginx, CI/CD, rollback.
- `06-memory-context-agent.md`: compact session state and handoff context.

## Skill Rule

- UI/design work: UI, design, frontend, motion, taste skills.
- Backend/API work: TypeScript, Node, database, security, testing skills.
- Ops/deploy work: shell, nginx, systemd, deploy, release skills.
- Docs/research work: docs, writing, research skills.
- Do not call skills unless they materially improve the work.

## Hard Rules

- Do not add product CLI commands for this metadata.
- Do not connect `agents/PROJECT_STATE.md` to runtime behavior.
- Do not scan the whole repo by default.
- Do not create duplicate truth.
- Do not mix local private context with VPS shared truth.
- Do not treat generated artifacts as source.

## Completion Output

Every substantial task should end with:

- What changed.
- What stayed out of scope.
- Verification performed.
- Risks left.
- Next step.

