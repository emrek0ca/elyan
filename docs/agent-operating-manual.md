# Agent Operating Manual

This manual defines how AI coding agents must operate in Elyan.

## 1) Work Sequence
1. Read task and restate objective in technical terms.
2. Inspect impacted code paths before editing.
3. Map contracts and blast radius.
4. Implement smallest correct patch.
5. Run targeted verification.
6. Report exact files changed and residual risks.

## 2) Read-First Requirement
Before edits, inspect all relevant surfaces:
- Gateway/API: `core/gateway/server.py`
- Persistence and repos: `core/persistence/runtime_db.py`
- Agent finalization/learning: `core/agent.py`
- Session bridge and draft promotion: `core/runtime/session_store.py`
- Skills/routines: `core/skills/manager.py`, `core/scheduler/routine_engine.py`
- Desktop route/onboarding/api client: `apps/desktop/src/app/routes.tsx`, `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`, `apps/desktop/src/services/api/*`
- CLI command path if CLI-affecting: `cli/main.py` + `cli/commands/*`

## 3) Contract Discipline
- Do not change endpoint semantics without updating all callers.
- Do not break loopback auth assumptions.
- Do not break cookie/session/CSRF handshake.
- Do not break workspace isolation checks.
- Do not break learned draft queue/promote flow.

## 4) Minimal-Patch Discipline
- Prefer targeted edits.
- Avoid broad rewrites in monolith files unless task explicitly requires it.
- Keep naming and style consistent with nearby code.
- Do not introduce secondary systems when one already exists.

## 5) Verification Discipline
For each non-trivial change:
- Run targeted tests for touched subsystem.
- Run local command checks for changed entry points.
- Validate success and failure path behavior.

For docs-only changes:
- Skip heavy test suites unless requested.
- Still verify references/paths/endpoints are real.

## 6) Reporting Discipline
Always report:
- Objective addressed.
- Files changed.
- Commands/tests run.
- What was not run.
- Known gaps/risks remaining.

## 7) Anti-Hallucination Rules
- Never invent APIs, endpoints, commands, or tables.
- Never claim behavior not verified in repo code.
- If code and docs conflict, document code reality and mark gap.
- If uncertain, state uncertainty and choose a reversible safe path.

## 8) Security Baseline
- Preserve existing security checks by default.
- Do not move tokens into URLs.
- Do not weaken signature validation.
- Do not remove upload/path validation.
- Do not bypass approval and policy gates.
