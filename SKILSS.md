# Elyan Live Handoff

Read `AGENTS.md` first. This file is the current continuation brief for the next coding agent.

Last updated: 2026-03-22

Current state snapshot:

- The onboarding/setup hang was fixed.
- The starter Ollama model is `llama3.2:3b`.
- `elyan launch` is the preferred one-command demo and operator entrypoint.
- `elyan status` now reports launch readiness, missing pieces, and the next action.
- `setup` and `onboard` still preserve `--skip-deps` and `--no-dashboard`.
- Completion lists include `launch`.
- The recent work also added focused tests for launch, status, CLI routing, and bootstrap behavior.
- The dashboard now has a more minimal control-plane layout.
- A new `Channels` tab manages configured messaging channels from the dashboard.
- Settings now cover runtime behavior, safety toggles, and tool policy in one place.
- Channel upsert accepts `original_id`, so edits and renames update the same record instead of duplicating it.
- Short chat-like inputs such as `kemal` now skip planner/task synthesis and use layered chat fallback first.
- `core/agent.py` now imports `get_conversation_context_manager` and guards conversation-context assembly so the process path no longer hits a `NameError`.
- The compatibility planner JSON parse is hardened, so malformed LLM output falls back cleanly.
- Gateway fallback copy is now operator-friendly instead of the old generic apology string.
- Added regression tests for short-chat routing, layered chat fallback, and invalid planner JSON fallback.

Relevant files:

- `elyan/bootstrap/onboard.py`
- `elyan/bootstrap/dependencies.py`
- `elyan/bootstrap/__init__.py`
- `cli/commands/launch.py`
- `cli/commands/status.py`
- `cli/commands/completion.py`
- `cli/main.py`
- `core/gateway/server.py`
- `bot/core/agent.py`
- `bot/core/intelligent_planner.py`
- `bot/core/gateway/router.py`
- `core/gateway/router.py`
- `ui/web/dashboard.html`
- `ui/web/dashboard.js`
- `bot/tests/unit/test_bot_agent_short_chat.py`
- `bot/tests/unit/test_intelligent_planner.py`
- `tests/unit/test_agent_routing.py`
- `tests/unit/test_bootstrap_dependencies.py`
- `tests/unit/test_bootstrap_manager.py`
- `tests/unit/test_launch_command.py`
- `tests/unit/test_status_command.py`
- `tests/unit/test_cli_main.py`

Verified:

- `python -m py_compile cli/commands/launch.py cli/commands/status.py cli/commands/completion.py cli/main.py tests/unit/test_launch_command.py tests/unit/test_status_command.py tests/unit/test_cli_main.py`
- `pytest -q tests/unit/test_bootstrap_dependencies.py tests/unit/test_cli_main.py`
- `pytest -q tests/unit/test_bootstrap_manager.py`
- `pytest -q tests/unit/test_launch_command.py tests/unit/test_status_command.py tests/unit/test_cli_main.py`
- `python -m py_compile bot/core/agent.py bot/core/intelligent_planner.py bot/core/gateway/router.py core/gateway/router.py bot/tests/unit/test_bot_agent_short_chat.py bot/tests/unit/test_intelligent_planner.py`
- `pytest -q bot/tests/unit/test_bot_agent_short_chat.py bot/tests/unit/test_intelligent_planner.py`
- `python -m py_compile core/agent.py tests/unit/test_agent_routing.py`
- `pytest -q tests/unit/test_agent_routing.py -k 'short_chat_falls_back_without_planner or chat_fast_path_when_llm_missing or uses_chat_fast_path_for_greeting or information_question_bypasses_planner_when_parser_is_chat'`

Current next step:

- Smoke-test the gateway with `kemal`, `adın`, and `ne` so the next agent can confirm the fallback path is clean in the live runtime.

Continuity rules:

- Do not revert unrelated workspace changes; the tree is intentionally dirty.
- Prefer the smallest correct diff.
- Keep launch and status behavior stable.
- Update this file after each meaningful change so the next agent inherits the current state.
