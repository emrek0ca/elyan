# Elyan - Canonical Project Guide


## Mission
- Build Elyan as a compact, self-hosted, privacy-first AI answering engine.
- Keep the product smaller, clearer, more reliable, and easier to run.
- Prefer a direct answer experience over a link-dump interface.
- Use web sources, readable citations, and streamed responses.
- Add only features that are clean, high-value, and actually finish end to end.

## Product Truth
- The core loop is: ask -> retrieve -> read -> answer -> cite.
- Search modes are `speed` and `research`.
- SearxNG is the private web search layer when available, but it is optional in the primary local path.
- Providers may be Ollama, OpenAI, Groq, or Anthropic.
- The UI must stay honest. No placeholder screens, dead routes, or fake controls.
- Document Q&A, widgets, and learning are not allowed to leak into the main UX unless they are fully wired and simple.

## Current Active Surface
- `src/app/page.tsx`: home entry point.
- `src/app/chat/new/page.tsx`: new chat entry.
- `src/app/chat/[id]/page.tsx`: existing chat entry.
- `src/app/chat/[id]/ChatInterface.tsx`: chat shell and composer.
- `src/app/api/chat/route.ts`: answer orchestration endpoint.
- `src/core/agents/answer-engine.ts`: unified speed/research retrieval and streaming.
- `src/core/search/*`: optional SearxNG client, reranker, scraper, citation context.
- `src/core/providers/*`: provider adapters and model resolution.
- `src/components/*`: search bar, message renderer, sidebar, layout.
- `src/app/globals.css`: the only design system file that should matter.
- `docker-compose.yml`: optional advanced deployment stack.
- `Dockerfile`: optional advanced container build.

## What Actually Matters
- Search and research are the primary answer modes, with local-only degraded answers when search is unavailable.
- Provider choice should be a compact model selection, not a settings maze.
- Inline citations should stay visible and readable in the answer body.
- Partial retrieval failure is acceptable if the system stays explicit and does not invent sources.
- The UI should explain itself in the first 5 seconds.

## What Is Intentionally Out
- Document upload and document RAG.
- Widgets such as weather or stock cards.
- Learning systems, memory promotion, feedback dashboards, and self-modifying behavior.
- Auth, accounts, and saved conversation history.
- Large control-plane screens for settings or library unless they directly control a real feature.
- Uncontrolled local computer access or silent background automation.

## Operating Rules
- Remove code before adding code when a feature can be simplified.
- Merge layers when they do the same job.
- Keep abstractions only when they reduce real complexity.
- Delete dead routes, dead components, dead state, and dead config.
- Do not keep placeholder behavior in the main path.
- Make failure states explicit, small, and debuggable.
- Prefer a single strong implementation over parallel weak ones.
- Do not add new dependencies unless the feature clearly needs them.

## Runtime Rules
- `/api/chat` must validate the request and only accept supported modes.
- The answer engine should resolve a model from the configured provider and stream one answer back.
- Search should use SearxNG when available and scrape only the sources needed for the answer.
- Research mode may do a slightly broader retrieval pass, but it should still be one code path with different config, not a separate system.
- If a provider or search dependency is missing, fail clearly instead of pretending to work.
- Redis is not a required core dependency unless a later feature truly needs it.
- PostgreSQL is not part of the active launch path unless persistence is deliberately introduced.

## Model and Provider Rules
- Ollama is the default local provider.
- OpenAI, Groq, and Anthropic are cloud options when API keys exist.
- Model selection must be understandable in the chat flow.
- Provider code should stay thin and predictable.
- Avoid fake failover systems unless they are actually implemented and tested.

## Search and Citation Rules
- Use SearxNG JSON search when available.
- Rerank before scraping.
- Scrape only a small number of the best URLs.
- Build prompt context from the retrieved content, not from invented knowledge.
- Answers should cite sources inline with `[1]`, `[2]`, etc.
- Do not fabricate citations when no sources are available.

## UI Rules
- The interface should be clean, calm, and fast.
- Use one visual language consistently.
- Avoid template-looking spacing, empty chrome, and decorative clutter.
- Loading, empty, and error states must be honest.
- Sidebar navigation should only show working surfaces.
- Mobile and desktop should both be legible without special cases exploding the code.

## Design Skill Preference
- For UI redesign, premium frontend polish, HTML prototypes, animation demos, and visual exploration, prefer the installed `huashu-design` and taste-family skills over generic frontend output.
- Use `huashu-design` for HTML-first design artifacts, concept exploration, prototype flows, and design review.
- Use project-local `design-taste-frontend`, `gpt-taste`, `redesign-existing-projects`, and `full-output-enforcement` when refining or generating frontend interfaces inside Elyan.
- Do not force these skills onto backend or systems work; apply them where they materially improve UI quality.

## Agent Skills Vs Runtime Capabilities
- Agent-side skills are development helpers only. They can live globally or under `.agents/skills` for repo reproducibility.
- Elyan runtime capabilities are product/runtime integrations only: local capability modules, MCP objects, Playwright, Crawlee, and other explicit runtime boundaries.
- Never describe a Codex/agent skill as an Elyan runtime feature unless it has been integrated through a real runtime surface.

## `find-skills` Usage
- Use `find-skills` when the request is about agent workflow extension, discoverability, or whether a Codex skill exists for a task.
- Prefer project-local `.agents/skills` when the Elyan repo should reproduce a shared development workflow.
- Prefer runtime modules or MCP integrations when the Elyan product itself needs the behavior.

## Deployment Rules
- Docker is optional and should stay simple if kept for advanced deployment.
- Every required runtime dependency must be listed plainly.
- Keep the environment file small and honest.
- Local setup should not depend on hidden services or undocumented steps.
- If a service is optional, make that clear.

## Build Rules
- `npm run lint` and `npm run build` must stay green.
- Fix the actual blocker, not the symptom.
- Avoid introducing code paths that only work in dev.
- If a route or component is not part of the product, remove it.

## Source Map By Former Document

### `README.md`
- Summarized v1 as a self-hosted web search and research app with citations and streamed answers.
- Documented local setup, Docker, and basic checks.
- That content now belongs in this file and should not live separately.

### `ROADMAP.md`
- Described an overgrown phased plan: foundation, providers, search, UI, documents, widgets, learning, production.
- It was useful as a wishlist, but most phases were speculative or too large for launch.
- The only useful part is the reminder that document RAG, widgets, and learning are later systems, not launch blockers.

### `TAKEOVER_AUDIT.md`
- Reported what was working, partial, misleading, duplicated, risky, and launch-blocking.
- Key findings were that the search/chat core worked, while documents, settings, widgets, learning, and persistence were mostly surface area without backing workflows.
- The main lesson is to keep the product center small and honest.

### `LAUNCH_SCOPE.md`
- Defined v1 as search, research, citations, and streamed answers.
- Explicitly excluded documents, auth, history, widgets, and learning.
- The practical rule was to hide or remove unsupported surfaces from the launch path.

### `ARCHITECTURE_DECISIONS.md`
- Chose a modular monolith inside Next.js.
- Separated app routes, core agents, search, providers, storage, and UI.
- Kept failure handling explicit and deferred async jobs, persistence, and learning to later phases.
- This should now be read as the architecture baseline, not as permission to grow layers.

### `BUILD_SEQUENCE.md`
- Said to make the repo green first, freeze scope, tighten the chat contract, remove placeholder surfaces, decide persistence only when needed, and grow post-launch.
- The main point was sequencing: stabilize first, expand later.

### `TECH_DEBT_REGISTER.md`
- Listed persistence not wired, duplicated search/research pipelines, hard external dependencies, unused learning schema, and mostly static provider management.
- That debt is still real unless a later change intentionally removes or wires it.

### `gemini.md`
- Re-stated the product as a privacy-first self-hosted answer engine.
- Repeated the original phase plan for provider support, search, RAG, widgets, learning, and production polish.
- It is useful only as historical context; do not treat it as a current scope promise.

### `skills/00-project-overview.md`
- Framed Elyan as a self-hosted, privacy-first AI Q&A search engine.
- Emphasized privacy, model-agnostic provider support, continuous evolution, and developer friendliness.

### `skills/01-architecture-guide.md`
- Described a modular monolith with presentation, application, core, and infrastructure layers.
- Documented the intended request flow from UI to chat route to router to agent to provider.
- Included service dependencies, module boundaries, error handling, security, caching, and conventions.
- The useful takeaway is separation of concerns, not the original scale of the plan.

### `skills/02-llm-integration.md`
- Described a provider registry over the Vercel AI SDK.
- Covered Ollama, OpenAI, Groq, and Anthropic.
- Proposed provider health checks, failover chains, and settings-driven model selection.
- The useful part is provider abstraction; the rest should stay minimal until it is actually needed.

### `skills/03-search-pipeline.md`
- Documented the retrieval stack: SearxNG, reranking, scraping, and citation-context assembly.
- Described Redis caching in the original plan.
- The useful takeaway is private web search plus cleaned source extraction plus inline citations.

### `skills/04-rag-pipeline.md`
- Described a future document pipeline: loader, chunker, embeddings, vector store, retriever, and document Q&A.
- This is deferred work and should stay out of the main path until it can be implemented cleanly with minimal moving parts.

### `skills/05-learning-engine.md`
- Described feedback collection, shared knowledge, user profiles, source reliability, and prompt optimization.
- This is a future controlled-learning system, not a launch feature.

### `skills/06-widget-system.md`
- Described a registry-based widget system for weather and stock data.
- Useful only if it is cleanly integrated and does not fragment the main answer flow.

### `skills/07-ui-design-system.md`
- Described the intended visual language: dark, glassmorphic, premium, with strong spacing and typography rules.
- The useful parts are clarity, restraint, readable hierarchy, and consistent surfaces.

### `skills/08-deployment-guide.md`
- Described the original multi-container deployment with Postgres, Redis, ChromaDB, SearxNG, and Ollama host integration.
- The important lesson is that deployment must be explicit and reproducible, but the stack should not be larger than the shipped product requires.

## Public Distribution (V1 Release)

Elyan V1 is explicitly distributed under three official channels to ensure real-world utility:
1. **Web Deployment**: Run directly on Node.js for the primary local path; Docker remains an optional advanced deployment path.
2. **NPM CLI Interface**: Publishable directly to npm (`npm install -g elyan`) serving commands like `elyan doctor`, `elyan config`, and `elyan start`.
3. **Homebrew Formula**: Packaged internally within `release/homebrew.rb` representing explicit macOS native deployment boundaries.

## Quickstart & Deployment

### Local Development / CLI
1. **Install CLI Wrapper**:
   `npm install -g .` (Inside repository)
2. **Configure Globals**:
   `elyan config set OPENAI_API_KEY=sk-...` (persists securely to `~/.elyan/.env`)
3. **Verify Environment**:
   `elyan doctor`
4. **Boot**:
   `elyan dev` (For development) or `elyan start` (for the direct local Node.js runtime).

### Production Deployment (Optional Docker)
Elyan is built to be deployed directly on Node.js for the main local path.
Docker Compose remains an optional advanced path for VPS/self-host users who prefer it.

1. Ensure `.env` is populated with the local runtime values you need.
2. Build and stand up the stack:
   `npm run build && npm run start`
3. The app is exposed on port `3000`. Add SearxNG only if you want live web retrieval and citations.

## Working Standard For Future Changes
- Consult `EXTENSIONS.md` before attempting to bolt external behavior (Widgets, RAG) into the core workflow.
- Elyan's architecture is closed. Keep the product center small, rigid, and strictly focused on fast search indexing and response mapping.

Continue from the current Elyan codebase. Do NOT restart from scratch. Do NOT drift back into feature chaos.

First, correct your mental model:

Elyan is NOT just a hosted search app.
Elyan is a local-first, Jarvis-like, multi-LLM personal agent product.

The hosted VPS is NOT the user’s private brain.
It is the shared Elyan control plane:
- accounts
- subscriptions
- billing
- token/credit accounting
- plan entitlements
- hosted access via elyan.dev
- global non-personal improvement signals
- optional remote integrations

User-private context, local files, local actions, device state, and personal workflows must remain local by default.

## TRUE PRODUCT MODEL

Elyan has 3 layers:

1. LOCAL AGENT RUNTIME
- primary product
- installed on the user’s computer or self-hosted on the user’s own server
- local-first
- supports multi-LLM routing
- supports local Ollama models and cloud models
- supports capabilities/tools/actions
- supports real work on the user’s machine
- keeps private local context local by default

2. SHARED VPS CONTROL PLANE
- not a dump of user-private memory
- stores only what the product/business needs:
  - accounts
  - billing
  - subscriptions
  - token/credit balances
  - entitlements
  - global routing / config policies
  - hosted web access
  - product-level improvement/evaluation signals
- no centralization of users’ private local lives by default

3. HOSTED WEB SURFACE
- elyan.dev is the public site and hosted access surface
- users should be able to chat there
- but hosted Elyan does not replace the local-first product
- hosted is an access and business surface, not the full personal runtime

## IMPORTANT RESEARCH DIRECTION

Take inspiration from OpenMythos-style thinking, but treat it correctly:
- it is a theoretical reconstruction, not a verified Claude blueprint
- use it as inspiration for architecture principles, not as dogma

The useful ideas to bring into Elyan are:
- compute-adaptive reasoning depth
- staged reasoning flow instead of one flat pass
- explicit recurrent/iterative refinement where useful
- modular specialist capability routing
- sparse activation / selective tool usage instead of “everything every time”
- controlled improvement loops
- architecture that can get better over time without turning into chaos

Translate that into Elyan’s product reality:
- not one giant monolithic agent
- not infinite feature sprawl
- not fake self-improvement theater
- instead: staged orchestration, capability routing, evaluation loops, and controlled promotion of learned improvements

## WHAT ELYAN SHOULD BECOME

Elyan should be a professional local-first personal operator that:
- can answer
- can retrieve and cite
- can use multiple LLMs in parallel or selectively
- can use local and cloud models
- can execute tools/capabilities safely
- can evolve through measured learning and evaluation
- can improve its capability layer over time
- can be installed locally, self-hosted by users, and also accessed via elyan.dev

## ARCHITECTURAL DIRECTION

Move the current Elyan codebase toward this structure without starting over:

### A. Keep the strong current core
Preserve and harden:
- ask -> retrieve -> read -> answer -> cite

### B. Build staged orchestration
Refactor Elyan toward explicit stages:
1. intent / mode classification
2. planning / routing
3. retrieval / context gathering
4. tool/capability invocation
5. synthesis
6. citation / output shaping
7. evaluation hooks
8. optional learning signal capture

Do NOT make this giant or abstract for no reason.
Make it concrete, typed, and testable.

### C. Multi-LLM intelligence
Elyan should support:
- local Ollama models
- cloud models
- model selection / fallback
- optional parallel model use where justified
- model routing based on task type, latency, cost, and privacy

But:
- do not create wasteful “all models all the time” behavior
- use selective routing, fallback, and comparison only where real value exists

### D. Capability system
Keep expanding Elyan through clean capabilities:
- retrieval
- documents
- charts
- browser actions
- MCP integrations
- local automation
- future memory/learning/eval systems

Every capability must have:
- typed schemas
- timeout policy
- auditability
- disable flags
- clear boundary
- no silent dangerous side effects

### E. Controlled self-improvement
Elyan should improve over time, but professionally.

Do NOT build vague AGI-ish self-modification.

Instead build toward:
- evaluation hooks
- quality scoring
- retrieval outcome scoring
- tool success/failure signals
- draft/promote flow for learned improvements
- global non-personal improvement signals on the VPS control plane
- personal/private context kept local unless explicitly synced

### F. MCP and capability growth
Mythos-like inspiration should help Elyan become stronger in:
- MCP integrations
- tool specialization
- capability routing
- selective compute depth
- iterative reasoning where valuable

But:
- do not turn MCP into a giant framework
- do not centralize private user state on the VPS
- do not let experimental systems pollute the stable core

## BUSINESS / PRICING / TOKENS

Think like a serious product operator and marketer.

Design Elyan’s pricing and token/credit model around the true product:

1. Local / BYOK plan
- cheap entry point
- user provides own keys or uses local models
- minimal platform fee
- strongest privacy story

2. Cloud-assisted plan
- monthly subscription
- includes hosted credits
- covers Elyan-managed cloud usage and hosted web usage

3. Pro / Builder plan
- higher limits
- more credits
- richer multi-LLM routing
- more advanced capabilities
- better task throughput

4. Team / Business direction
- per-seat logic
- admin controls
- team entitlements
- hosted governance
- privacy guarantees

Requirements:
- user-facing pricing must be simple
- internal accounting can be more detailed
- credit/token logic must map to real infra/API cost
- local-first usage should stay attractive
- hosted usage should be metered professionally
- abuse control and rate limiting should exist
- upgrade triggers should be obvious

## WHAT YOU MUST DO NOW

Take the current codebase and move it toward this actual product identity.

1. Audit current structure against the real Elyan model
2. Align code into:
   - local runtime
   - shared VPS control plane
   - hosted web surface
3. Preserve the current strong core
4. Strengthen local-first runtime as the primary product
5. Keep the VPS side narrow and correct
6. Prepare elyan.dev as a hosted answer surface
7. Design a professional pricing / token / entitlement model
8. Leave the project in a state where I can test Elyan locally on my computer

## END-OF-TASK REQUIREMENT

When you finish:
- I must be able to run Elyan locally
- test current capabilities on my machine
- see clearly what is local vs VPS vs hosted
- understand the recommended pricing/token model
- get exact final commands to run on my computer

## INSPIRATION

You may take inspiration from:
- OpenMythos for staged, compute-adaptive, selective reasoning ideas
- Claude Code for operator ergonomics and tooling discipline
- OpenClaw for self-hosted personal-agent deployment thinking

But do NOT copy them blindly.
Build Elyan for Elyan:
a local-first personal agent, with a shared control plane, a hosted web surface, disciplined capability growth, and professional continuous improvement.

## NON-NEGOTIABLE RULES

- do not start over
- do not break the current solid core
- do not centralize private user data by default
- do not bloat the architecture
- do not add fake surfaces
- do not turn the VPS into personal memory storage
- do not let learning systems silently mutate stable behavior
- prefer mature libraries over brittle custom plumbing
- remove weak code when strong library integration replaces it

## OUTPUT FORMAT

At the end, report only:
- what you changed in architecture
- what belongs local vs VPS vs hosted
- what you designed for pricing/token accounting
- what code you changed
- what I can test locally right now
- the exact commands I should run on my computer
- the last real blocker, if any
