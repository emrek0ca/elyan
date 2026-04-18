# SKILLS.md

This file defines Elyan's current skill/routine/learned-draft system based on actual implementation.

## 1) Scope and Reality
Elyan has three related but different concepts:
- Skill: executable capability manifest managed by `core/skills/manager.py`.
- Routine: scheduled automation definition managed by `core/scheduler/routine_engine.py`.
- Learned draft: candidate learned from interactions, queued in runtime DB and manually promotable.

This document is normative for contributor behavior and descriptive for current code reality.

## 2) What Is a Skill?
A skill is a named capability package with metadata, required tools, and runtime readiness checks.

Current storage and control plane:
- Manifest path: `~/.elyan/skills/<skill_name>/skill.json`
- Manager: `core/skills/manager.py`
- Enabled list: config key `skills.enabled`
- API endpoints: `/api/skills*` in `core/gateway/server.py`
- CLI: `elyan skills ...` via `cli/commands/skills.py`

### Skill lifecycle (current)
1. Discover from builtin catalog (`core/skills/catalog.py`) and installed manifests.
2. Install (`install_skill`) creates/loads `skill.json` and enables skill.
3. Enable/disable toggles config membership in `skills.enabled`.
4. Edit updates manifest fields (`edit_skill`).
5. Health check validates tools/dependencies and policy access (`check`).
6. Remove deletes local manifest directory.

## 3) What Is a Routine?
A routine is a persisted scheduled workflow with cron expression, steps, channel delivery settings, and run history.

Current storage and control plane:
- Persistence file: `~/.elyan/routines.json`
- Reports: `~/.elyan/reports/routines/<YYYYMMDD>/*.md`
- Engine: `core/scheduler/routine_engine.py`
- API endpoints: `/api/routines*` in `core/gateway/server.py`
- CLI: `elyan routines ...` + `elyan schedule ...`

### Routine lifecycle (current)
1. Create from:
   - template (`/api/routines/from-template`),
   - natural language (`/api/routines/from-text`),
   - explicit payload (`/api/routines`),
   - learned draft (`/api/routines/from-draft`).
2. Persist in `routines.json` with metadata/history counters.
3. Sync to cron runtime through gateway cron bridge.
4. Run manually (`/api/routines/run`) or via schedule.
5. Toggle enabled/disabled.
6. Remove by id.

## 4) What Is a Learned Draft?
A learned draft is a queued proposal extracted from user interaction, not automatically activated as skill/routine.

Generation path:
- `core/agent.py` `_finalize_turn` -> `_queue_learning_drafts`
- extractor: `core/learning/draft_extractor.py`

Queue storage path:
- `core/persistence/runtime_db.py` tables:
  - `preference_update_queue`
  - `skill_draft_queue`
  - `routine_draft_queue`

Read/review surfaces:
- API: `GET /api/learning/drafts`
- CLI: `elyan memory drafts`

Promotion path:
- Skills: `/api/skills/from-draft` -> `RuntimeSessionAPI.promote_skill_draft`
- Routines: `/api/routines/from-draft` -> `RuntimeSessionAPI.promote_routine_draft`

Promotion updates draft status (`promoted`) and records promotion metadata.

## 5) Skill Manifest Minimum Schema
Minimum practical fields for local skill manifests:
- `name` (normalized, snake_case)
- `version`
- `description`
- `category`
- `source` (`builtin`, `local`, `curated`, etc.)
- `required_tools` (list)
- `commands` (list)

Strongly recommended:
- `integration_type`
- `auth_strategy`
- `fallback_policy`
- `required_scopes`
- `supported_platforms`
- `approval_level`
- `latency_level`
- `evidence_contract`
- `workflow_bundle` (if skill contributes workflow behavior)
- `python_dependencies`, `post_install`

## 6) Naming and Versioning Conventions
Skill naming:
- lowercase snake_case
- ASCII preferred
- action/domain focused (`browser`, `files`, `research`, not vague names)

Routine naming:
- human-readable, short, explicit intent
- avoid overloaded generic names like `routine-1`

Versioning:
- semantic style string in manifests (`1.0.0` etc.)
- increment when behavior/contract changes, not only cosmetics

## 7) Safety Boundaries
For skills and routines:
1. Never bypass runtime approval/policy boundaries.
2. Do not require dangerous tools without explicit reason.
3. Keep required tool list minimal and truthful.
4. Preserve runtime checks for missing/blocked tools.
5. Keep output/evidence expectations explicit when modifying workflow behavior.

For learned drafts:
- Do not auto-promote silently.
- Do not convert low-confidence ambiguous text into active automation without review.
- Keep draft metadata auditable (source action/channel/confidence).

## 8) Testing Expectations
When changing skill/routine/draft logic:
- Add or update targeted tests in relevant suites, for example:
  - `tests/unit/test_skill_manager.py`
  - `tests/unit/test_routines_cli.py`
  - `tests/test_runtime_persistence.py`
- Validate both happy path and failure path.
- For gateway contract changes, include endpoint-level tests.

## 9) How Claude Should Add a New Skill
1. Check if existing builtin/local skill already covers the use case.
2. Define minimal manifest fields and required tools.
3. Install skill through manager or create manifest in `~/.elyan/skills/<name>/skill.json` through manager flow.
4. Ensure `commands` map to real intent surface.
5. Run skill health check (`elyan skills check`).
6. Add/update tests for manager behavior or API exposure.

## 10) How Claude Should Modify an Existing Skill
1. Read current manifest and where it is consumed.
2. Update only necessary fields.
3. Re-run check flow for missing tools/dependencies.
4. Verify no route/intent regression in skill selection surface.
5. Add regression tests for changed behavior.

## 11) How Claude Should Add/Modify Routines
1. Prefer existing template/from-text flows before adding new routine abstractions.
2. Keep cron expression, channel, and steps explicit.
3. Ensure routine ids remain stable and resolvable.
4. Verify history and report persistence still works.
5. Validate API + CLI behavior (`/api/routines/*`, `elyan routines`, `elyan schedule`).

## 12) What Not To Do
- Do not invent a parallel skill store.
- Do not store routine state in ad-hoc extra files when engine already persists `routines.json`.
- Do not auto-enable risky skills by default without policy review.
- Do not silently mark drafts as promoted without creating real skill/routine object.
- Do not claim full autonomous learning when current pipeline is queue-and-review based.

## 13) Skill Spec Template (Practical)
```json
{
  "name": "example_skill",
  "version": "1.0.0",
  "description": "Short, explicit capability statement",
  "category": "custom",
  "source": "local",
  "integration_type": "desktop",
  "required_tools": ["tool_a", "tool_b"],
  "commands": ["example"],
  "required_scopes": [],
  "auth_strategy": "none",
  "fallback_policy": "native",
  "supported_platforms": ["darwin", "linux", "windows"],
  "approval_level": 0,
  "latency_level": "standard",
  "evidence_contract": {
    "requires_artifact": false,
    "requires_verification": true,
    "preferred_signal": "runtime_log"
  }
}
```

## 14) Routine Spec Template (Practical)
```json
{
  "id": "auto_generated",
  "name": "Daily Operational Check",
  "expression": "0 9 * * *",
  "steps": [
    "Open source panel",
    "Check updates",
    "Prepare summary",
    "Send report"
  ],
  "enabled": true,
  "report_channel": "telegram",
  "report_chat_id": "",
  "template_id": "",
  "tags": ["daily"],
  "metadata": {
    "created_by": "cli-or-api"
  }
}
```

## 15) Draft Promotion Checklist
Before promoting any draft:
1. Draft exists and status is promotable (`draft` or `approved`).
2. Name/description is meaningful and non-empty.
3. Required tool/schedule/channel fields are valid.
4. Promotion target actually created (skill manifest or routine object).
5. Draft status updated to `promoted` with metadata.
6. Gateway/CLI surfaces reflect promoted object.

## 16) Known Gaps (Current Code Reality)
- Two skill registry concepts exist:
  - Active path: `core/skills/registry.py` + `core/skills/manager.py`
  - Legacy/alternate path: `core/runtime/skill_registry.py`
- Routine storage is file-based (`~/.elyan/routines.json`), not runtime DB table-backed.
- Learned draft extraction is heuristic keyword/parser based, not robust semantic intent learning.

Contributors must preserve current contracts while improving these areas incrementally.
