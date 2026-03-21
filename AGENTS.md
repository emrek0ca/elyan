# Elyan AGENTS.md

This file is the single source of truth for working on Elyan.
All other markdown docs in this repo are intentionally removed so this file can stay canonical.

## 1. Mission

Elyan is a local-first AI operator that turns natural language into real work.
It is not a chat app. It is an operator stack with planning, tool use, sandboxing, approvals, evidence, learning, and automation.

Primary product goal:
- Convert intent into safe action.
- Prefer local execution first.
- Require evidence before claiming completion.
- Keep the system investor-demo ready and production safe.

## 2. Canonical Architecture

The current codebase is split into clear surfaces:

- `elyan/` is the canonical onboarding, sandbox, approval, actuator, learning, and capability layer.
- `core/` is the main runtime layer: control planes, gateway, skills, integrations, memory, reliability, LLM routing, and compatibility bridges.
- `tools/` is the tool registry and lazy-loaded execution surface.
- `cli/` contains command entrypoints and wrappers.
- `integrations/` contains provider/connectors and registry logic.
- `ui/` and `bot/` contain UI and compatibility surfaces that still mirror parts of the runtime.

Use the canonical layer first:
- New bootstrap and onboarding work belongs in `elyan/bootstrap/`.
- Security and approval belong in `elyan/approval/` and `elyan/core/security.py`.
- New capability packages belong in `core/<capability>/` plus a tool wrapper and skill entry.
- Keep legacy compatibility paths alive only when they are still called by active code.

## 3. Runtime Flow

The runtime pipeline is:

1. User input enters through CLI, dashboard, gateway, or a messaging adapter.
2. The request is normalized into a unified internal request.
3. The operator control plane classifies intent and decides whether it is:
   - a fast local command,
   - a planning problem,
   - a multi-step task,
   - a skill/integration action,
   - or a clarification request.
4. The selected skill/tool is executed through the task executor.
5. The security layer checks approval and sandbox policy before risky actions.
6. The real-time actuator performs UI or browser work when needed.
7. The verifier collects trace, evidence, and artifacts.
8. The learning layer stores feedback, outcomes, and preference signals.
9. Autopilot uses those signals for maintenance, briefing, and proactive suggestions.

Fast-path order used by the system:
- response cache
- quick intent match
- chat fast path
- intent parser
- task engine
- delivery/state machine path

## 4. Algorithms and Math

### 4.1 Intent routing

Elyan uses a tiered intent system:

- Tier 1: exact/fuzzy pattern matching for common requests.
- Tier 2: semantic classification using an LLM when the request is less obvious.
- Tier 3: deep reasoning when the task is ambiguous, multi-step, or high stakes.

Operationally, routing prefers the cheapest reliable answer first.
The decision score is a weighted combination of:

- memory match
- exact pattern match
- fuzzy match
- semantic confidence
- user context
- tool availability
- risk penalty

Useful mental model:

`final_score = w_memory * memory + w_pattern * pattern + w_semantic * semantic - w_risk * risk + w_context * context`

If confidence is high enough, the system executes.
If confidence is low or the action is risky, it clarifies or asks approval.

### 4.2 Thresholds

Use the documented tier thresholds as default behavior:

- Fast path should be effectively instantaneous for simple requests.
- Semantic classification should stay under a few hundred milliseconds when possible.
- Deep reasoning is reserved for the hard cases.
- A confidence around `0.7` is a practical return threshold for classified intent.

### 4.3 Retrieval and RAG

Document and second-brain retrieval uses a mix of:

- lexical overlap
- tokenization
- topic overlap
- embedding similarity
- top-k ranking
- citation extraction

Common score model:

`retrieval_score = a * cosine_similarity + b * topic_overlap + c * lexical_overlap`

The system should:
- return grounded answers when possible,
- attach citations or source snippets,
- never claim certainty when evidence is weak,
- and degrade to a partial answer rather than fabricating.

### 4.4 Learning math

Learning is progressive, not binary.
Use the following mental model:

- success rewards are positive
- failures reduce confidence and may increase retries or fallback use
- consecutive successes raise the reward multiplier
- repeated corrections create stronger memory

Typical metrics:

- `success_rate = successes / max(total, 1)`
- `avg_latency = sum(latency_ms) / max(total, 1)`
- `p95/p99` latency should be tracked for routing and operator UX

Learning levels are conceptually:

- exact match
- fuzzy match
- semantic match
- autonomous reasoning

### 4.5 Circuit breaker and reliability

The reliability layer uses circuit breaker semantics:

- track failures per tool/provider
- open the breaker after a threshold
- recover after a timeout window
- reset on success

Model:

`breaker_open = failure_count >= threshold`

Use partial success when part of a task succeeds and part fails.
Never collapse a partially successful mission into a full failure unless the failed part blocks the goal.

### 4.6 Approval and sandbox math

Approval levels are ordered:

- `NONE`
- `CONFIRM`
- `SCREEN`
- `TWO_FA`
- `MANUAL`

Higher risk actions must move up this ladder.
Destructive actions must never run as zero-approval defaults.

Sandbox defaults should remain:

- read-only filesystem
- no network unless explicitly allowed
- `cap_drop=ALL`
- `no-new-privileges`
- low memory and CPU limits
- unprivileged user

### 4.7 Cost control

The system should optimize for:

- cached answers first
- small models or local models first when enough
- expensive models only when required
- consensus or multi-provider routing only when the task justifies it

## 5. Capabilities

Elyan currently covers these capability families:

- CLI control and diagnostics
- dashboard mission control
- gateway HTTP/WebSocket runtime
- browser automation
- desktop and screen control
- file and project operations
- office/document processing
- research and RAG
- voice and media workflows
- messaging adapters
- autopilot maintenance and proactive suggestions
- learning and persistent memory
- multi-agent and sub-agent task decomposition
- sandboxed execution
- approval-gated destructive actions
- Quivr-style second brain workflows
- Lean/formal-method style project orchestration
- Cloudflare Agents style project orchestration
- OpenGauss-style database project orchestration

Major product surfaces:

- `elyan status`, `doctor`, `health`, `dashboard`, `gateway`
- `elyan skills`, `integrations`, `models`, `memory`
- `elyan autopilot`, `cron`, `webhooks`, `security`
- `elyan browser`, `voice`, `agents`, `quota`
- public dashboard trace and evidence views
- onboarding and bootstrap flows

Supported channel families:

- Telegram
- WhatsApp
- Discord
- Slack
- Matrix
- Signal
- Microsoft Teams
- iMessage / BlueBubbles
- Google Chat
- Web chat

Supported knowledge and workflow families:

- Quivr second brain
- document RAG
- research workflows
- office files
- generated app packs
- code/project scaffolds
- live project packs with shared `/api/packs` overview, readiness, feature counts, and command rails

## 6. Technologies

Core runtime stack:

- Python 3.11+
- `pydantic`
- `aiohttp`
- `httpx`
- `requests`
- `click`
- `json5`
- `croniter`
- `sqlalchemy`
- `psutil`

LLM and local model stack:

- Groq
- Google Gemini
- Ollama
- optional cloud fallback providers in docs and config

AI / retrieval / ML stack:

- `numpy`
- `scikit-learn`
- `sentence-transformers`

Document and office stack:

- `beautifulsoup4`
- `lxml`
- `Pillow`
- `python-docx`
- `openpyxl`
- `pdfplumber`
- `pypdf`
- `python-pptx`
- `reportlab`

Scheduling and runtime automation:

- `apscheduler`
- `feedparser`
- `watchdog`

Security and secret handling:

- `cryptography`
- `keyring`
- Docker-based sandboxing

Platform and UI integrations:

- `playwright`
- `PyQt6`
- `python-telegram-bot`
- `discord.py`
- `slack-bolt`
- platform optional packages for Windows, macOS, and Linux

Operational runtimes documented and used in code:

- `aiohttp` gateway and adapter server
- Screenpipe for desktop capture / MCP workflows
- Ollama for local models and vision fallback
- FastAPI only where generated/demo app packs require it

## 7. Working Rules For Changes

Follow these rules on every task:

- Prefer the smallest correct diff.
- Do not break working behavior.
- Do not rename public interfaces unless required.
- Do not change schemas unless the migration is explicit.
- Do not rewrite whole files when a targeted patch is enough.
- Do not modify unrelated modules.
- Preserve compatibility wrappers until all callers are migrated.
- Keep the zero-permission default unless the user explicitly asks to relax it.
- Never weaken approval requirements for destructive actions.
- Prefer one shared live overview endpoint over per-card dashboard fetches.
- For pack/status surfaces, keep the data model compact, actionable, and copy-friendly.

For every non-trivial task:

1. Understand the goal, constraints, and runtime context.
2. Choose the minimum number of files to touch.
3. Make the change.
4. Verify the change locally.
5. Stop when the goal is reached.

When a task is inferable, act instead of asking unnecessary questions.
When uncertainty is high, inspect first and then patch.

## 8. Change Patterns

### Adding a new capability

If you add a new domain capability:

- create a canonical package under `core/<capability>/` or `elyan/<capability>/`
- add a lazy tool wrapper in `tools/<capability>_tools.py`
- register it in `tools/__init__.py`
- add or update a builtin skill in `core/skills/builtin/`
- register it in the skill catalog
- update the capability router and process profiles if routing should detect it
- add a focused test file

### Adding a new integration

If you add a new provider or connector:

- update the integration registry
- expose a connector/adapter
- wire it into onboarding if users need one-click setup
- add trace/evidence surfaces if it can act on user data
- document fallback behavior and failure states in code or AGENTS

### Adding a new tool

Every tool should return a structured payload with:

- `success`
- `status`
- `message`
- `error` when needed
- `data`
- `artifacts`
- `evidence`
- `metrics`

If a tool result is ambiguous, normalize it before exposing it to the operator runtime.

### Changing sandbox or approval logic

Security work must preserve:

- zero-permission default
- explicit destructive-action approval
- auditability
- deterministic failure modes
- clear rollback or refusal behavior

### Changing LLM routing

Keep the provider stack local-first:

- local model first when sufficient
- cheap provider next
- quality provider when the task needs it
- fallback chain always available

## 9. Data, State, and Runtime Locations

Canonical runtime state lives under `~/.elyan/`:

- `config.json5` for configuration
- `gateway.pid` for gateway process state
- `autopilot/` for autopilot state
- `memory/` for memory and indices
- `logs/` for logs
- `skills/` for installed skills
- `sandbox/` for sandbox workspace
- `browser/` for browser profiles and sessions
- `projects/` for workspaces
- `backups/` for snapshots and recovery
- `runs/` for mission or execution records

Treat these as user data, not source code.

## 10. Test Strategy

Use tests where risk is real:

- approval and security changes
- sandbox behavior
- routing and task execution
- gateway, dashboard, or websocket work
- tool normalization and contract changes
- onboarding and bootstrap changes

Prefer targeted tests over full-suite runs unless the change crosses several layers.

Good validation patterns:

- syntax check for edited Python files
- focused unit tests for the changed module
- one smoke command for the affected CLI or tool
- one integration check for the gateway or dashboard when relevant

Do not create unnecessary test noise.

## 11. Operational Style

Communication and execution style:

- stay concise
- be explicit about what changed
- do not narrate unnecessary details
- use direct, factual status updates
- keep user-facing messages short for messaging channels
- keep logs technical and precise

Behavioral rules:

- search memory before asking the user when the task may repeat
- reuse existing capabilities before inventing new ones
- suggest automation when a task is repeated often
- do not behave statelessly

## 12. Current Roadmap

Current priorities:

- unified onboarding
- zero-permission sandbox
- approval matrix
- dashboard trace and evidence viewer
- investor-facing docs and release packaging

Next priorities:

- migrate the OperatorControlPlane fully to the canonical `elyan/core` runtime
- ship a public skill store with install-from-repo flows
- improve the evidence gallery and video export UX
- polish dashboard and CLI UX to a Codex-level operator experience
- add command palette, faster navigation, and clearer trace/evidence drilldowns
- keep project pack cards action-oriented with live readiness, feature counts, and copyable commands
- finish OpenGauss database workspace scaffolding and SQL query loop
- finish public release packaging for launch

Later priorities:

- enterprise policies and SSO
- cloud fallback tier
- multi-agent authoring workflows
- public template gallery

## 13. Practical Notes For Future Work

- Update this file instead of creating new markdown docs.
- If a feature spans multiple layers, update all layers in one pass.
- If a feature touches runtime contracts, update tests immediately.
- If a legacy path remains, keep the compatibility adapter small.
- If a change reduces safety, reject it unless the user explicitly asks and the risk is acceptable.

Elyan should always feel like a fast, local-first operator with traceable actions, safe defaults, and strong execution quality.

## 14. Codex-Quality Bar

This repo should be maintained at Codex-level quality:

- Work in small, reviewable, mechanically clear diffs.
- Prefer explicit boundaries over clever abstractions.
- Preserve public behavior unless the change is intentionally breaking.
- Keep files focused on one responsibility.
- Remove duplication only when the new shape is simpler and easier to reason about.
- Keep runtime paths boring, deterministic, and easy to debug.
- Treat developer ergonomics as a product feature.
- Do not introduce hidden behavior, side effects, or implicit magic.
- Keep the repo stable while improving it; do not destabilize working flows for architectural aesthetics.

If a task can be completed with a surgical patch, do that instead of a broad refactor.
If a broader refactor is required, stage it so behavior remains valid at every step.

## 15. UI/UX Standards

UI and operator surfaces must look and feel professional:

- Favor calm, readable, purposeful layouts.
- Keep information density high but not noisy.
- Make task status, trace, evidence, and next action obvious at a glance.
- Prefer clear hierarchy, consistent spacing, and legible typography.
- Use polished empty states, loading states, and error states.
- Every user-visible flow should feel intentional, not assembled.
- Dashboard and CLI wording should be concise, consistent, and operator-friendly.
- For visible UI changes, verify the rendered experience, not only the code path.

When improving UI, optimize for:

- fast comprehension
- low cognitive load
- clear primary action
- traceability of what happened
- a demo-ready first impression

## 16. No Code Chaos

Code chaos is not acceptable in this repository.

- Do not scatter related logic across unrelated files.
- Do not create micro-abstractions that make tracing execution harder.
- Do not split a coherent flow into too many layers unless it reduces complexity.
- Do not leave duplicate implementations in parallel without a clear migration plan.
- Do not make cleanup commits that silently alter behavior.
- Do not add noisy comments, dead code, or speculative scaffolding.
- Do not weaken structure in the name of speed.

Preferred shape:

- one concept per module
- one execution path per responsibility
- one canonical source of truth per domain
- one clear compatibility layer only when migration requires it

When in doubt, choose the simpler implementation that keeps the whole stack easy to understand.

## 17. Verification And Migration Discipline

Before merging a meaningful change:

- verify the edited path locally
- check that the user-visible behavior still matches expectations
- confirm the migration path if an old and new implementation coexist
- update tests for behavior, contracts, or UI surfaces that changed
- update docs only when they materially help the next maintainer or operator

Migration rules:

- preserve current behavior first
- introduce the new canonical path
- keep a minimal compatibility adapter only as long as needed
- remove legacy paths after callers are moved
- never leave two competing sources of truth without a reason

If a change affects onboarding, dashboard, trace, evidence, or approval flows, treat it as high risk and verify the full chain end to end.
