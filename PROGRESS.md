# Elyan

Elyan is a local-first AI operator with CLI, dashboard, gateway, skills, integrations, and sandboxed execution.

## Quick Install

```bash
curl -fsSL https://get.elyan.ai | bash
```

If you already cloned the repo:

```bash
bash install.sh --headless --no-ui
```

## Workspace Bootstrap

First run creates `agents.md` and `memory.md` in the workspace root, plus legacy `AGENTS.txt` / `MEMORY.txt` artifacts for compatibility.

## Monorepo Layout

- `elyan/core` - control plane, skill registry, learning
- `elyan/actuator` - real-time actuator
- `elyan/integrations` - connector surface
- `elyan/cli` - CLI entrypoints
- `elyan/dashboard` - dashboard surface
- `elyan/gateway` - gateway/runtime surface
- `elyan/sandbox` - isolated execution
- `elyan/docs` - docs scaffold

