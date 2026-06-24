# Elyan Skill and Capability Protocol

## Purpose
Elyan skills are structured capabilities selected by the backend brain and executed through the approved system path. A skill is not a free-form prompt trick. It has a purpose, triggers, input schema, output schema, timeout, validation, and safety expectations.

## Routing
- Use backend skill definitions as the source of truth for active skills.
- Use corpus context to improve skill selection, not to bypass the skill registry.
- Attachment questions should prefer document or vision skills when extracted chunks are available.
- Desktop/private side effects must route to desktop runtime, not backend direct execution.
- Mobile remains a sender and renderer; it does not call local engines directly.

## Skill Behavior
- Use only the evidence provided to the skill.
- Return structured output when the skill definition requires it.
- If attachment chunks are insufficient, say so clearly.
- Do not invent pages, files, objects, or external facts that are not present.
- Keep tool calls explicit, bounded, timeout-limited, and permission-gated.

## Capability Boundaries
- Backend can reason, route, retrieve, summarize, and orchestrate metadata.
- Desktop runtime executes local files, browser, computer, MCP, private automation, and side-effectful tools.
- Side-effect tools require permission and traceable task IDs.
- Missing capabilities should degrade safely with a clear blocked reason.
