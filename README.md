# Elyan v1

Elyan is a local-first personal agent runtime.

The real v1 product surface is small:

- local chat runtime
- local health and readiness
- capability discovery
- dashboard
- CLI
- optional search
- optional MCP
- optional channels
- optional narrow hosted control-plane integration

Everything else is secondary.

## Canonical Local Path

1. Copy the environment file:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
npm install
```

3. Start Ollama and make sure at least one model is available, or set one cloud API key in `.env`:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

4. Run Elyan:

```bash
npm run dev
```

Or production-like:

```bash
npm run build
npm run start
```

5. Check health:

- `http://localhost:3000/api/healthz`

6. Inspect capabilities:

- `http://localhost:3000/api/capabilities`

7. Use Elyan:

- `http://localhost:3000`
- `http://localhost:3000/manage`

## What Is Required

You need one usable model source:

- local Ollama at `OLLAMA_URL`, or
- one cloud provider key

Without a model source, Elyan is not ready.

## What Is Optional

### Search

SearXNG is optional.

If it is reachable, Elyan uses live retrieval and citations.
If it is missing, Elyan stays usable in local-only mode.

### MCP

MCP is optional.

Only configure it if you actively use MCP servers.

### Channels

Telegram, WhatsApp Cloud, WhatsApp Baileys, and iMessage/BlueBubbles are optional.

Only enable them if you have their real runtime credentials or bridge setup.

### Hosted control plane

The shared VPS control plane is optional.

It is only for shared business/product state such as:

- accounts
- plans
- subscriptions
- entitlements
- hosted usage accounting

Private local runtime state stays local by default.

## Dashboard And CLI

These are the real control surfaces.

Dashboard:

- `http://localhost:3000/manage`

CLI:

```bash
npm install -g .
elyan doctor
elyan health
elyan status
elyan capabilities
elyan settings view
```

## First-Run Checks

- `/api/healthz`: tells you if Elyan is actually ready
- `/api/capabilities`: shows the runtime capability surface
- `/manage`: shows runtime state, optional integrations, and optional hosted state

## Environment

Base local runtime:

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
```

## License

Elyan is licensed under `AGPL-3.0-or-later`.

If you modify and deploy it as a network service, you must make the corresponding source available under the same terms.

## Security

- Public-facing hosted and control-plane routes use hardened HTTP headers and no-store defaults on private surfaces.
- Do not commit secrets, tokens, or private credentials to the repository.
- Report vulnerabilities privately through GitHub Security Advisories or `SECURITY` before public disclosure.

## Product Boundary

Elyan v1 is not:

- a Docker-first product
- a platform
- a feature pile
- a fake hosted everything-app

Elyan v1 is a directly runnable local-first runtime that degrades cleanly when optional systems are absent.
