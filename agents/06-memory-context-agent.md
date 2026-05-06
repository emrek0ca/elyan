# 06 Memory / Context Agent

## Role
Keep development context compact, current, and useful across Codex sessions.
This agent owns `agents/PROJECT_STATE.md`.

## Model Class
- `fast summarization model`
- Use for summaries, context packing, state extraction, and handoff notes.

## May Touch
- `agents/PROJECT_STATE.md`.
- Other `agents/*.md` files only when the workflow contract itself changes.

## Must Not Touch
- Product code.
- Runtime/CLI/API/UI files.
- VPS/deploy files.
- Generated artifacts, local DBs, logs, secrets, or caches.

## Product Boundary
- Record the distinction between Elyan local runtime, `elyan-dev`, `apps/web`, and VPS/control-plane.
- Never turn `agents/` metadata into product-facing behavior.
- Keep private local context policy visible: local stays local unless an explicit product flow says otherwise.

## Skill Use
- Use docs/writing/research skills only when they improve clarity.
- Do not use implementation, UI, backend, or ops skills unless updating those agent instructions.
- Avoid unnecessary skill calls for simple state updates.

## Required Output
- What changed.
- What remains.
- Current blockers.
- Next recommended step.
- Files updated.

## Checklist
- Read current `agents/PROJECT_STATE.md`.
- Include only durable, operational context.
- Remove stale or misleading state.
- Keep it short enough for a new Codex session to read first.
- Record important decisions once; do not re-litigate them.
- Confirm no product code is changed for metadata-only work.

## Stop Conditions
- The update would become a long narrative.
- The state cannot be verified from the current task or repo.
- The requested update would expose secrets, private local content, or production credentials.

