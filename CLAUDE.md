# CLAUDE.md

## 1) Project Identity
Elyan is a local-first personal agent runtime, not a generic chatbot.

What Elyan is in this repository:
- `core/gateway/server.py`: primary aiohttp gateway and product API surface.
- `core/agent.py`: central orchestration and learning finalization flow.
- `core/persistence/runtime_db.py`: runtime database schema and repositories.
- `core/run_store.py`: canonical run persistence + runtime DB mirror.
- `core/runtime/session_store.py`: conversation/auth-session bridging + draft promotion.
- `core/scheduler/routine_engine.py`: routine definitions, NL routine generation, history, persistence.
- `core/skills/manager.py`: skill lifecycle for local manifests under `~/.elyan/skills`.
- `apps/desktop/src/*`: desktop UX for onboarding, auth, readiness, stack.

What Elyan is not:
- Not a stateless prompt responder.
- Not cloud-only.
- Not “feature-complete SaaS” yet; multi-user foundations exist but defaults remain local-first (`local-workspace`, `local-user`).

## 2) Non-Negotiable Rules
1. Read before edit. Never patch blind.
2. Preserve existing contracts unless explicitly changing them with tests.
3. No large refactors in high-risk files without explicit task scope.
4. No fake readiness claims.
5. No placeholder/stub/TODO implementations in production paths.
6. No silent exception swallowing for critical flows.
7. No auth/session/security weakening for convenience.
8. No broad abstractions unless repeated concrete need is proven.
9. Keep diffs minimal and reviewable.
10. If uncertain, choose safer and reversible changes.

## 3) Mandatory Pre-Edit Inspection
For every task, inspect the relevant surfaces first:
- API/contract changes: `core/gateway/server.py`, `apps/desktop/src/services/api/elyan-service.ts`, `apps/desktop/src/services/api/client.ts`
- Auth/session/cookies/CSRF: `core/gateway/server.py`, `core/persistence/runtime_db.py` (`LocalAuth*` repos), `apps/desktop/src/app/providers/AppProviders.tsx`
- Memory/drafts/routines/skills: `core/agent.py`, `core/learning/draft_extractor.py`, `core/runtime/session_store.py`, `core/persistence/runtime_db.py`, `core/scheduler/routine_engine.py`, `core/skills/manager.py`
- Onboarding/readiness UX: `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`, `apps/desktop/src/app/routes.tsx`, `core/gateway/server.py` (`/healthz`, `/api/v1/system/overview`)
- Persistence changes: `core/persistence/runtime_db.py` only (schema source of truth)
- CLI behavior: `cli/main.py` + specific command module

## 4) Runtime/Auth/Session Contracts (Do Not Break)
- Loopback restriction is intentional:
  - User session/admin access are localhost-only via `_is_loopback_request`.
- User session acceptance path:
  - `X-Elyan-Session-Token` header OR `elyan_user_session` cookie.
  - Admin token fallback is only loopback + valid admin token.
- CSRF enforcement applies to session-protected write requests; login/bootstrap routes are explicit exceptions.
- Dashboard websocket auth is message-based (`{"type":"auth","token":...}`), not URL token.
- Desktop auth hydration path:
  - `GET /api/v1/auth/me` via cookie/session and `AppProviders.tsx` hydration.

If changing any of the above, add/adjust tests and document migration impact.

## 5) Persistence and Data Rules
- Runtime schema lives in `core/persistence/runtime_db.py` (table declarations + repositories).
- Use SQLAlchemy `text()` + named params for raw SQL execution.
- Do not introduce parallel migration systems for runtime DB in normal feature work.
- Keep workspace/user scoping explicit; avoid accidental fallback to wrong actor/workspace.
- Sensitive payloads should remain encrypted/redacted as implemented by runtime repositories.

## 6) Skills / Routines / Learned Drafts Rules
- Skills:
  - Managed by `core/skills/manager.py`.
  - Persisted as `~/.elyan/skills/<skill_name>/skill.json`.
  - Enabled set stored in config key `skills.enabled`.
- Routines:
  - Managed by `core/scheduler/routine_engine.py`.
  - Persisted in `~/.elyan/routines.json`.
  - Created via template, NL text, or draft promotion.
- Learned drafts:
  - Produced in `core/agent.py` `_queue_learning_drafts` using `core/learning/draft_extractor.py`.
  - Stored in runtime DB draft queues.
  - Promoted via `core/runtime/session_store.py` methods and API endpoints `/api/skills/from-draft` and `/api/routines/from-draft`.

Never invent a separate draft/skill/routine pipeline without explicit migration strategy.

## 7) LLM and Provider Principles
- Respect local-first preference and current provider/model role mapping.
- Do not hardcode a provider/model in business logic unless task explicitly requires it.
- Keep provider health and fallback behavior compatible with:
  - `core/llm/provider_pool.py`
  - `core/llm/model_selection_policy.py`
  - `core/llm/ollama_discovery.py`

## 8) UI/UX Principles for Elyan Desktop
- Clean, calm, high-signal UI.
- Show real system state; avoid fake “AI is working” illusions.
- Onboarding must reflect actual backend readiness (`setup_complete`, provider/channel/routine state).
- Do not clutter with speculative controls.
- Keep navigation and auth guard behavior stable (`apps/desktop/src/app/routes.tsx`).

## 9) Security and Privacy Policy (Contributor-Level)
- Do not loosen localhost restrictions casually.
- Do not expose secrets/tokens in URLs, logs, or persisted plaintext.
- Preserve upload safety checks (MIME whitelist, size limit, filename/path sanitation).
- Preserve webhook signature verification behavior.
- Preserve privacy/consent surfaces under `/api/v1/privacy/*`.
- Keep memory/privacy controls truthful: local-first by default, explicit consent for broader learning.

## 10) Multi-User Readiness Rules
- Assume future multi-user SaaS, even when current flow is local-first.
- Keep workspace_id/actor_id/session scoping explicit.
- Preserve workspace isolation checks on run/thread/billing/connectors endpoints.
- Avoid introducing single-tenant shortcuts in shared repositories.

## 11) Test Policy
- For risky logic changes, run targeted tests in touched area.
- For contract changes, add/update tests before merge.
- If pre-existing failures exist, do not mask them; report what you ran and what is unrelated.
- For docs-only changes, do not run full test suite unless requested.

## 12) Release Priorities (Current)
Before private beta quality claims, prioritize:
1. Onboarding → login/bootstrap → readiness continuity.
2. Skill/routine visibility and draft promotion reliability.
3. Task execution safety (approval, verification, audit trace).
4. Desktop + gateway error-state clarity.
5. Workspace isolation and privacy controls.

## 13) Forbidden Behaviors
- Blind edits without reading impacted code paths.
- Breaking auth/session or route guards to unblock UI quickly.
- Adding dead/unused parallel systems instead of wiring existing flow.
- Marking incomplete subsystems as production-ready.
- Massive diffs for cosmetic rewrites.
- Disabling tests to force green.
- Replacing secure compare/validation with weaker checks.

## 14) Delivery Format for Claude Sessions
For every substantial task, report:
- Objective and affected contracts.
- Files changed.
- Risks considered.
- Verification commands run and outcomes.
- Known gaps left intentionally.
