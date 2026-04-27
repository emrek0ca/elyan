# Elyan v1.3

Elyan is a local-first personal agent runtime with a separate hosted control plane on elyan.dev.

The real v1 product surface is intentionally small:

- local chat runtime
- local health and readiness
- capability discovery
- dashboard
- CLI
- optional search
- optional MCP
- optional channels
- optional hosted control-plane integration

Everything else is secondary.

## Canonical Local Path

1. Install dependencies:

```bash
npm install
```

2. Prepare local storage, safe environment defaults, and zero-cost model routing:

```bash
npm install -g .
elyan setup --zero-cost
```

If the CLI is not linked globally yet:

```bash
node bin/elyan.js setup --zero-cost
```

`elyan setup` runs the safe bootstrap path, checks local model/search reachability, and prints the next local-first step without requiring hosted account linking.

3. Start Ollama and pull the recommended local model if setup reports that Ollama is not reachable:

```bash
elyan models setup
```

Cloud keys are optional and should only be set when you intentionally want cloud inference:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

4. Run Elyan:

```bash
npm run dev
```

Production-like:

```bash
npm run build
npm run start
```

5. Check health and open the command center:

- `http://localhost:3000/api/healthz`
- `http://localhost:3000/manage`

## What Is Required

You need one usable model source:

- local Ollama at `OLLAMA_URL`, or
- one cloud provider key

Zero-cost mode uses local Ollama and local storage. Without a model source, Elyan is not ready.

## CLI

```bash
elyan setup --zero-cost
elyan doctor
elyan doctor --fix --zero-cost
elyan health
elyan status
elyan status --json
elyan capabilities
elyan settings view
elyan open
```

Local operator permissions:

```bash
elyan desktop status
elyan desktop grant .
elyan desktop enable
```

Service mode:

```bash
elyan service install
elyan service start
elyan service status
```

Channel diagnostics:

```bash
elyan channels list
elyan channels doctor
elyan channels setup telegram
elyan channels test telegram
```

MCP diagnostics:

```bash
elyan mcp list
elyan mcp doctor
elyan mcp enable <server>
elyan mcp disable <server>
elyan mcp disable-tool <server> <tool>
```

v1.3 operator runs:

```bash
elyan run --mode research "compare local-first agent runtimes with sources"
elyan run --mode code "inspect this repo and plan a safe patch"
elyan run --mode cowork "plan the next product milestone"
elyan runs list
elyan runs show <runId>
elyan approvals list
elyan approvals approve <approvalId>
elyan approvals reject <approvalId>
```

Operator runs are local-first planning records. Each run records an adaptive reasoning profile (`shallow`, `standard`, or `deep`) so Elyan can stay fast for simple work and slow down for research, code, cowork, and verification-heavy tasks. Runs also track quality gates for the selected mode: research needs sources or an honest unavailable state, code needs repository inspection plus approval-safe verification, and cowork needs inspectable role artifacts. Risky file, terminal, browser, MCP, or automation actions must still pass typed action, policy, approval, audit, and verification before execution.

Hybrid quantum-inspired optimization:

```bash
elyan optimize demo assignment
elyan optimize demo resource-allocation --json
```

The v1.3 optimization capability is TEKNOFEST-oriented decision support, not a separate quantum chatbot. It models assignment and resource-allocation problems, builds a QUBO representation, compares greedy, simulated annealing, and small brute-force QUBO fallback solvers, then returns an auditable JSON plus Markdown decision report. No real quantum hardware is claimed or required.

## Optional Surfaces

### Search

SearXNG is optional. If it is reachable, Elyan uses live retrieval and citations. If it is missing, Elyan stays usable in local-only mode.

### MCP

MCP is optional. Only configure it if you actively use MCP servers.

### Channels

Telegram, WhatsApp Cloud, WhatsApp Baileys, and iMessage/BlueBubbles are optional.

- Telegram uses the official Bot API and supports polling or webhook mode.
- WhatsApp Cloud is the official Meta surface and can incur template-message costs.
- WhatsApp Baileys is local best-effort and unofficial; it is not a guaranteed business channel.
- iMessage requires a local BlueBubbles server on a Mac with iMessage available.

### Hosted Control Plane

The shared VPS control plane is optional and only for shared business/device state:

- accounts
- sessions
- plans
- subscriptions
- entitlements
- hosted usage accounting
- device linking and token rotation
- notifications and ledger entries

Private local runtime state stays local by default.

## Local Operator Safety

The local operator is permissioned computer control, not unrestricted system takeover.

- It is disabled until enabled in runtime settings or through `elyan desktop enable`.
- It can only operate inside configured `allowedRoots`.
- Sensitive paths such as `.env`, SSH keys, cloud credentials, wallets, shell profiles, and system directories are protected by default.
- Write, destructive, and system-critical actions require explicit approval policy levels.
- Evidence is written under `ELYAN_STORAGE_DIR/evidence`.

## Environment

Base local runtime:

- `ELYAN_STORAGE_DIR=storage`
- `ELYAN_RUNTIME_SETTINGS_PATH=storage/runtime/settings.json`
- `OLLAMA_URL=http://127.0.0.1:11434`
- `SEARXNG_URL=http://localhost:8080`

Optional cloud providers:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

Optional hosted control plane:

- `DATABASE_URL`
- `NEXTAUTH_URL`
- `NEXTAUTH_SECRET`
- `IYZICO_API_KEY`
- `IYZICO_SECRET_KEY`
- `IYZICO_MERCHANT_ID`

Optional MCP:

- `ELYAN_MCP_SERVERS`
- `ELYAN_DISABLED_MCP_SERVERS`
- `ELYAN_DISABLED_MCP_TOOLS`

## Commands

```bash
npm run lint
npm run test
npm run build
npm run release:check
```

## Security

- Public-facing hosted and control-plane routes use hardened HTTP headers and no-store defaults on private surfaces.
- Do not commit secrets, tokens, or private credentials to the repository.
- Do not grant broad local operator roots unless you are comfortable with that machine scope.
- Report vulnerabilities privately through GitHub Security Advisories or `SECURITY` before public disclosure.

## Product Boundary

Elyan v1.3 is not:

- a Docker-first product
- a fake hosted everything-app
- an unrestricted computer-control bot
- a replacement for explicit channel credentials and platform rules

Elyan v1.3 is a directly runnable local-first runtime with guided setup, safer release/install surfaces, and a clearer operator workflow. The hosted surface is separate and only adds shared account and billing features when configured.

## License

Elyan is licensed under `AGPL-3.0-or-later`.

If you modify and deploy it as a network service, you must make the corresponding source available under the same terms.
