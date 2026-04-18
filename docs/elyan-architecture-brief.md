# Elyan Architecture Brief

A fast orientation document for contributors. This reflects current repository reality.

## 1) Primary Runtime Topology
- Main entrypoint: `main.py` (`_run_gateway`)
- Primary server: `core/gateway/server.py` (aiohttp)
- Primary orchestrator core: `core/agent.py`
- Primary persistence: `core/persistence/runtime_db.py` + `core/run_store.py`
- Desktop client: `apps/desktop/src/*` (React + Vite/Tauri shell)

## 2) Data and Ownership Model
Current defaults are local-first:
- workspace defaults frequently resolve to `local-workspace`
- actor/user defaults frequently resolve to `local-user`

However runtime DB includes multi-workspace tables and access control repositories:
- workspaces, memberships, invites, seat assignments
- connector accounts/traces/health
- billing events/ledger/entitlements
- conversation sessions/messages with workspace+actor scoping

## 3) Gateway/API Layer
`core/gateway/server.py` provides:
- auth endpoints: `/api/v1/auth/bootstrap-owner`, `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`
- readiness/health: `/healthz`, `/api/v1/system/overview`, `/api/v1/system/platforms`
- skills: `/api/skills*`
- routines: `/api/routines*`
- learning drafts: `/api/learning/drafts`
- privacy: `/api/v1/privacy/*`
- billing/connectors/cowork endpoints

Security model (current):
- local loopback enforcement for sensitive access paths
- session via `X-Elyan-Session-Token` or `elyan_user_session` cookie
- admin token for admin scope on loopback
- CSRF checks on protected browser mutation routes

## 4) Session and Conversation Model
- Auth sessions: `LocalAuthSessionRepository` in runtime DB
- Conversation sessions/messages: `ConversationRepository`
- Session bridge/hydration: `core/runtime/session_store.py`
- Desktop auth hydration uses `/api/v1/auth/me`

## 5) Skills / Workflows / Routines / Drafts
Skills:
- manager: `core/skills/manager.py`
- registry resolver: `core/skills/registry.py`
- manifests: `~/.elyan/skills/<name>/skill.json`
- enabled skills tracked in config (`skills.enabled`)

Workflows:
- builtin workflow catalog from `core/skills/catalog.py`
- mission-recipe-derived workflows can be merged by manager

Routines:
- engine: `core/scheduler/routine_engine.py`
- persistence file: `~/.elyan/routines.json`
- reports: `~/.elyan/reports/routines/...`

Learned drafts:
- generated in `core/agent.py` using `core/learning/draft_extractor.py`
- queued in runtime DB draft queue tables
- promoted through API+session store (`/api/skills/from-draft`, `/api/routines/from-draft`)

## 6) LLM / Model Layer
- model policy: `core/llm/model_selection_policy.py`
- provider health cooldown: `core/llm/provider_pool.py`
- local model discovery: `core/llm/ollama_discovery.py`

## 7) Desktop App Surface
Key flows:
- route guards: `apps/desktop/src/app/routes.tsx`
- onboarding: `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`
- API adapter: `apps/desktop/src/services/api/elyan-service.ts`
- auth/cookie client: `apps/desktop/src/services/api/client.ts`
- runtime/websocket bridge: `apps/desktop/src/app/providers/AppProviders.tsx`, `runtime-socket.ts`

## 8) Known Architectural Gaps
1. Legacy parallel surfaces exist:
- `api/http_server.py` (Flask-based server) vs primary aiohttp gateway.
- `core/runtime/skill_registry.py` differs from active `core/skills/*` path.

2. Routine persistence is file-based, not unified in runtime DB.

3. Some runtime modules under `core/runtime/*` appear partial/legacy and are not the main production path compared to gateway+agent integration.

4. Multi-user foundations exist but product defaults and onboarding remain local-single-user oriented.

## 9) Practical Guidance
When adding features:
- treat gateway + runtime DB + desktop API adapter as the contract triangle.
- preserve auth/session/workspace semantics.
- avoid introducing a new parallel subsystem if an active one exists.
