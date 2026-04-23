# CAPABILITY_LIBRARY_MAP.md

This is the binding capability decision document for Elyan.

Rule: a capability is not part of Elyan unless it is listed here as implemented or explicitly deferred with a reason.
This file describes Elyan runtime capabilities only. It does not describe Codex/agent-side skills under `.agents/skills`.

## Principles

- Prefer one strong library per capability.
- Replace brittle custom code when a mature library clearly does the job better.
- Do not expose capability surfaces without schemas, timeout handling, audit records, disable flags, and tests.
- Do not add “nice to have” capabilities that increase maintenance more than user value.
- Controlled dependency updates only: no blind latest pulls.

## Implemented capabilities

### `fuzzy_find`
- Library: `fuse.js`
- Why: best fit for typo-tolerant ranking, compact, dependency-free, mature.
- Used for: local fuzzy ranking and search-result ordering.
- Replaces: custom token-includes ranking logic.

### `math_exact`
- Library: `mathjs`
- Why: mature deterministic math engine with strong expression support.
- Used for: exact expression evaluation.

### `math_decimal`
- Library: `decimal.js`
- Why: precise decimal arithmetic without floating-point drift.
- Used for: currency-like and precision-sensitive calculations.

### `csv_parse`
- Library: `papaparse`
- Why: stable, fast CSV parsing with good edge-case handling.
- Used for: parsing structured CSV into rows.

### `csv_export`
- Library: `papaparse`
- Why: same library covers both parse and unparse cleanly.
- Used for: exporting row objects back to CSV.

### `docx_read`
- Library: `mammoth`
- Why: reliable DOCX text extraction with a narrow, proven API.
- Used for: extracting readable text from Word documents.

### `docx_write`
- Library: `docx`
- Why: direct DOCX generation without inventing a custom writer.
- Used for: simple document export.

### `pdf_extract`
- Library: `unpdf`
- Why: modern PDF text extraction with broad runtime support.
- Used for: text extraction from PDF inputs.

### `image_process`
- Library: `sharp`
- Why: production-grade image processing backed by libvips.
- Used for: metadata reads and safe image resize/convert operations.

### `web_read_dynamic`
- Library: `playwright`
- Why: best fit for rendering JS-heavy pages in a controlled, auditable browser runtime.
- Used for: extracting visible content after client-side rendering.

### `web_crawl`
- Library: `crawlee` with `@crawlee/cheerio`
- Why: purpose-built crawling orchestration with link following and request lifecycle control.
- Used for: bounded same-domain crawling and readable page extraction.

### `browser_automation`
- Library: `playwright`
- Why: the smallest mature browser automation layer for typed, auditable action sequences.
- Used for: short browser interactions that support retrieval or verification.

### `chart_generate`
- Library: `recharts`
- Why: compact React-native chart rendering with enough surface for Elyan’s internal visualization needs.
- Used for: summary computation plus static chart markup generation.

### `tool_bridge`
- Library: `ai` tools plus Elyan capability wrappers
- Why: typed tool execution with a clean path into capability execution without growing a separate agent system.
- Used for: invoking bounded internal tools through one audited bridge.

### `mcp_bridge`
- Library: `ai` tools plus the isolated `src/core/mcp` boundary
- Why: the capability exposes machine-readable bridge metadata while the live MCP client/runtime stays outside the Next.js request path.
- Used for: exposing bridge tools and configured MCP server contracts without collapsing local and remote execution into one runtime.

## Explicitly deferred capabilities

These remain out of the visible product and out of the launch path until there is a concrete, tested reason to add them.

### Browser automation / crawling
- `@browserbasehq/stagehand`
- Reason to defer: AI-guided browser workflows only add value if they lower maintenance versus plain Playwright; that case is not proven yet.

### Rich editor / authoring
- `@tiptap/*`
- Reason to defer: document editing is not part of the launch product.

### Charts / visualization
- `chart.js`
- Reason to defer: Recharts is implemented because it directly supports the current controlled capability boundary. Chart.js remains deferred as a second rendering option without a proven need.

### Desktop control
- `@nut-tree/nut-js`
- Reason to defer: local mouse/keyboard control is high risk, permission-heavy, and currently not part of the product boundary. The package identity was also not reliable in current registry checks.

### Long-running workflow graphs
- `@langchain/langgraph`
- Reason to defer: the current product does not need a stateful agent graph layer.

### AI SDK tools / MCP bridge
- Full MCP server hosting, multi-node orchestration, and general-purpose framework layering remain deferred.
- Reason to defer: the current implementation only needs a typed bridge, a live client boundary, and a small registry, not a full tool platform.

### PDF/image/doc future expansions
- Additional image generation/editing SDKs
- Richer document workflows beyond plain extraction and simple writing
- Reason to defer: add only when there is a visible product path and a test plan.

## Registry and runtime rules

Every capability that is enabled must:

- Have a typed `zod` input schema.
- Have a typed output schema.
- Enforce a timeout.
- Record an audit entry on success or failure.
- Support explicit disable flags.
- Have tests before it is made visible to any user-facing surface.

The runtime registry is the source of truth. If a capability is not registered there, it does not exist operationally.

## Dependency update policy

Controlled updates are mandatory.

- Use Renovate.
- Patch and minor updates: scheduled weekly PRs.
- Major updates: separate PRs.
- Merge only after lint, build, capability tests, and smoke checks pass.
- No automatic latest upgrades.

## Binding decision

For Elyan v1, capability growth is allowed only if it:

1. Has clear user value.
2. Uses a mature library.
3. Stays inside the current product boundary.
4. Comes with tests.
5. Replaces or prevents brittle custom code.

Anything else stays deferred.
