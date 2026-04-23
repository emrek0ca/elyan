# Agent Skills In This Repo

This directory is for project-local Codex/agent workflow helpers only.

## What lives here

- `huashu-design`
- `design-taste-frontend`
- `gpt-taste`
- `redesign-existing-projects`
- `full-output-enforcement`

These are installed project-locally so Elyan UI and frontend work can be reproduced across machines.

## Hard boundary

- Agent-side skills improve design review, prototyping, critique, and frontend refinement during development.
- They are not Elyan runtime capabilities.
- Elyan runtime only uses real runtime modules, MCP objects, Playwright, Crawlee, and other explicit product integrations.
- If you are changing Elyan itself, prefer the smallest runtime module, MCP surface, or capability that solves the problem.
- Do not invent new workflows, shadow systems, or hidden abstractions when an existing module can be tightened.

## When to use `find-skills`

Use the global `find-skills` skill when the request is about agent workflow extension:

- "How do I do X with Codex?"
- "Is there a skill for this?"
- "Find a skill for ..."

Do not use `find-skills` when the user is asking Elyan the product/runtime to gain a new feature.
For product work, prefer:

1. A local runtime capability/module
2. An MCP tool, resource, prompt, or resource template
3. A browser/crawl capability

When using an existing skill file, keep it aligned with the repo's actual stack and boundaries.
- Do not let a frontend skill drift into backend policy.
- Do not let a generic skill redefine Elyan's architecture.
- Update the guidance only when it removes confusion or prevents a real regression.

## Installation model

- Project-local skills live under `.agents/skills/` for repo reproducibility.
- Global skills live under `~/.codex/skills/` for machine-wide convenience.
- `find-skills` remains global and is not overridden here.
