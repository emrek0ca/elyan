from __future__ import annotations

import asyncio

import pytest

import core.cowork_threads as cowork_threads_module
import core.mission_control as mission_control_module
import core.persistence.runtime_db as runtime_db_module
import core.run_store as run_store_module
import core.workflow.vertical_runner as vertical_runner_module
from core.cowork_threads import get_cowork_thread_store
from core.persistence import reset_runtime_database
from core.run_store import get_run_store


@pytest.fixture(autouse=True)
def isolated_cowork_state(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ELYAN_RUNTIME_DB_PATH", str(tmp_path / "elyan" / "db" / "runtime.sqlite3"))
    cowork_threads_module._thread_store = None
    mission_control_module._mission_runtime = None
    run_store_module._run_store = None
    vertical_runner_module._vertical_workflow_runner = None
    runtime_db_module._runtime_database = None
    runtime_db_module._runtime_database_key = ""
    reset_runtime_database()
    yield
    cowork_threads_module._thread_store = None
    mission_control_module._mission_runtime = None
    run_store_module._run_store = None
    vertical_runner_module._vertical_workflow_runner = None
    runtime_db_module._runtime_database = None
    runtime_db_module._runtime_database_key = ""
    reset_runtime_database()


@pytest.mark.asyncio
async def test_cowork_thread_routes_website_lane_and_supports_follow_up():
    store = get_cowork_thread_store()

    created = await store.create_thread(
        prompt="Build a premium React landing page for Elyan with a calm hero and a clear CTA.",
        workspace_id="workspace-alpha",
        session_id="desktop-main",
        preferred_mode="website",
        project_template_id="launch-site",
        routing_profile="quality_first",
        review_strictness="strict",
    )

    assert created["thread_id"]
    assert created["current_mode"] == "website"
    assert created["active_run_id"]
    assert any(turn["role"] == "user" for turn in created["turns"])
    assert any(turn["role"] == "operator" for turn in created["turns"])

    run = None
    for _ in range(80):
        run = await get_run_store().get_run(str(created["active_run_id"]))
        if run and run.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.1)

    assert run is not None
    assert run.status == "completed"
    assert str((run.metadata or {}).get("thread_id") or "") == created["thread_id"]
    assert str((run.metadata or {}).get("workspace_id") or "") == "workspace-alpha"

    detail = await store.get_thread_detail(str(created["thread_id"]))
    assert detail["artifacts"]
    assert detail["goal"].startswith("Build a premium React landing page")
    assert detail["current_step"]
    assert detail["risk_level"] in {"low", "medium", "high"}
    assert isinstance(detail["tools_in_use"], list)
    assert detail["last_successful_checkpoint"] is not None
    assert any(action["id"] == "retry" for action in detail["control_actions"])
    assert isinstance(detail["replay"]["checkpoints"], list)

    follow_up = await store.add_turn(
        str(created["thread_id"]),
        prompt="Revise the CTA hierarchy and make the proof section more compact.",
        review_strictness="strict",
    )

    user_turns = [turn for turn in follow_up["turns"] if str(turn.get("role") or "") == "user"]
    assert len(user_turns) >= 2
    assert follow_up["active_run_id"]


@pytest.mark.asyncio
async def test_cowork_thread_can_run_general_mission_mode():
    store = get_cowork_thread_store()

    created = await store.create_thread(
        prompt="Review the current Elyan roadmap and suggest the next three priorities.",
        workspace_id="workspace-alpha",
        session_id="desktop-main",
        preferred_mode="cowork",
    )

    assert created["thread_id"]
    assert created["current_mode"] == "cowork"
    assert created["active_mission_id"]
    assert any(turn["role"] == "operator" for turn in created["turns"])
