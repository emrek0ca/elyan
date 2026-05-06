# Elyan Web

This workspace hosts the Next.js public site and hosted control plane for `elyan.dev`.
The local runtime lives at the repository root; this package only owns the hosted surface.

## Development

1. Install dependencies:

```bash
pnpm install
```

2. Start the hosted workspace locally:

```bash
pnpm dev
```

3. Build and run the app directly:

```bash
pnpm build
pnpm start
```

4. Run the workspace test suite:

```bash
pnpm test
```

5. Useful surfaces:

- `http://localhost:3000/api/healthz`
- `http://localhost:3000/manage`

## Local Control Plane

- Local backend port: `3013`
- Local PostgreSQL must be running and reachable through `DATABASE_URL`
- `pgvector` must be installed in the active PostgreSQL server
- Required hosted env for local backend startup: `DATABASE_URL`, `NEXTAUTH_URL`, `NEXTAUTH_SECRET`
- Run migrations with `pnpm db:migrate`
- Verify the full hosted flow with `pnpm verify:local-control-plane`
- Restart the backend process after changing `DATABASE_URL`, `NEXTAUTH_*`, or running migrations; stale server processes will keep old env and schema state
- `elyan-dev` should point to `http://127.0.0.1:3013` during local development

## Boundary

- `kodlar/elyan` is the local runtime/app layer: private user context, local tools, and local-first behavior stay there.
- `elyan-backend` is the control-plane layer: auth, account state, billing, devices, usage, learning metadata, and hosted API state live here.
- Private local context must never cross into the control-plane by default.

## Commands

```bash
pnpm lint
pnpm test
pnpm build
pnpm db:migrate
pnpm security:check
pnpm release:check
```

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
