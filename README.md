# Elyan AI Operator

[![CI](https://github.com/emrek0ca/elyan/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/emrek0ca/elyan/actions/workflows/ci.yml)
[![Release](https://github.com/emrek0ca/elyan/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/emrek0ca/elyan/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

Elyan is a local-first AI operator that turns natural language into real computer work, with sandboxing, approvals, evidence, and traceability built in.

It is designed to feel like a blend of:

- OpenClaw-style operator control
- Cursor Composer-style task execution
- Anthropic Claude Computer Use-style computer interaction

## What It Does

- Plans tasks from natural language
- Uses browser, desktop, email, calendar, and other integrations
- Runs actions in a zero-permission Docker sandbox by default
- Requires approval for destructive actions
- Stores trace, evidence, and delivery artifacts
- Learns from repeated workflows

## Quick Start

```bash
curl -fsSL https://get.elyan.ai | bash
elyan status
elyan dashboard
```

If you already have the repo locally:

```bash
bash install.sh --headless --no-ui
elyan bootstrap status
elyan doctor
elyan gateway start --daemon
elyan dashboard
```

## Core Surfaces

- `CLI`: operator control and diagnostics
- `Dashboard`: mission control, trace, evidence, integrations, skills
- `Gateway`: API and WebSocket runtime
- `Messaging`: Telegram and WhatsApp adapters
- `Autopilot`: maintenance and proactive suggestions

## Demo Flow

1. Install.
2. Open the dashboard.
3. Create a mission.
4. Watch the execution trace.
5. Review evidence and artifacts.

The investor-facing deck is available in [`docs/index.html`](./docs/index.html).

## Architecture

- `OperatorControlPlane` for planning and routing
- `SkillRegistry` and `IntegrationRegistry` for capability selection
- `RealTimeActuator` for browser and desktop control
- `SecurityLayer` for sandbox and approval enforcement
- `Verifier` for evidence and trace output
- `Autopilot` for maintenance and proactive operations

## Safety Model

- Zero-permission default
- Approval matrix for risky actions
- Docker isolation for execution
- Evidence-first completion
- Local-first storage and fallback routing

## Documentation

- [Product docs](./docs/README.md)
- [Investor deck outline](./docs/pitch-deck.md)
- [Docs site landing page](./docs/index.md)
- [Public release deck](./docs/index.html)

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Security

See [`SECURITY.md`](./SECURITY.md).

## Roadmap

See [`ROADMAP.md`](./ROADMAP.md).

## License

MIT. See [`LICENSE`](./LICENSE).
