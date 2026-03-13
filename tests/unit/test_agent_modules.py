from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.agents import context_recovery as context_recovery_mod
from core.agents import invisible_meeting_assistant as meeting_mod
from core.agents import website_change_intelligence as website_mod
from core.agents.registry import get_agent_module_spec, list_agent_modules, run_agent_module


def test_agent_module_catalog_contains_ten_modules():
    modules = list_agent_modules()
    ids = {row.get("module_id") for row in modules}
    assert len(modules) >= 10
    assert "context_recovery" in ids
    assert "digital_time_auditor" in ids


@pytest.mark.asyncio
async def test_run_agent_module_handles_unknown_and_existing_runner():
    unknown = await run_agent_module("does_not_exist", {})
    assert unknown["success"] is False
    assert unknown["error"] == "module_not_found"

    website = await run_agent_module("website_change_intelligence", {"tracked_urls": []})
    assert website["success"] is True
    assert website["status"] in {"no_targets", "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_id", "payload"),
    [
        (
            "automatic_learning_tracker",
            {"learning_items": ["AI agents orchestration memory systems planning algorithms"]},
        ),
        (
            "life_admin_automation",
            {"inbox_items": ["Invoice payment due tomorrow", "Subscription renew 2026-03-15"]},
        ),
        (
            "deep_work_protector",
            {"activity_events": [{"app": "Code", "duration_minutes": 120}, {"domain": "youtube.com", "duration_minutes": 30}]},
        ),
        (
            "ai_decision_journal",
            {"decisions": [{"decision": "Invest in AI orchestration", "category": "investment", "outcome": "success"}]},
        ),
        (
            "personal_knowledge_miner",
            {"file_paths": [__file__]},
        ),
        (
            "project_reality_check",
            {
                "project": {
                    "name": "Agent Ops Suite",
                    "roadmap": ["scheduler", "verification", "go-live"],
                    "tech_plan": "Multi-module architecture with deterministic tests",
                    "market_evidence": "3 paid pilot users and weekly usage growth",
                    "budget": 50000,
                    "team_size": 3,
                    "timeline_weeks": 12,
                }
            },
        ),
        (
            "digital_time_auditor",
            {"activity_blocks": [{"signal": "coding", "duration_minutes": 180}, {"signal": "youtube.com", "duration_minutes": 30}]},
        ),
    ],
)
async def test_run_agent_module_executes_all_new_runners(module_id: str, payload: dict):
    result = await run_agent_module(module_id, payload)
    assert result["success"] is True
    assert result.get("status") != "planned_only"
    assert result.get("module_id") == module_id
    if "report_path" in result:
        assert Path(str(result["report_path"])).exists()


@pytest.mark.asyncio
async def test_context_recovery_module_generates_dashboard(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "elyan_data"
    runs_root = data_dir / "runs"
    run_dir = runs_root / "run_1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(
        json.dumps(
            {
                "user_input": "Elyan agent scheduler kodu duzenlendi",
                "metadata": {"action": "scheduler_update"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "evidence.json").write_text(
        json.dumps({"metadata": {"status": "success"}, "steps": [], "artifacts": []}),
        encoding="utf-8",
    )

    desktop_dir = data_dir / "desktop_host"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    (desktop_dir / "state.json").write_text(
        json.dumps(
            {
                "frontmost_app": "Code",
                "active_window": {"title": "elyan scheduler patch"},
                "last_instruction": "Fix automation scheduler",
                "last_status": "success",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(context_recovery_mod, "resolve_elyan_data_dir", lambda: data_dir)
    monkeypatch.setattr(context_recovery_mod, "resolve_runs_root", lambda: runs_root)
    monkeypatch.setattr(context_recovery_mod, "_tail_history_commands", lambda limit=120: ["git status", "pytest -q"])

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    result = await context_recovery_mod.run_context_recovery_module({"workspace": str(workspace)})

    assert result["success"] is True
    assert result["module_id"] == "context_recovery"
    assert result["recent_runs"]
    assert result["yesterday_summary"]
    assert Path(result["report_path"]).exists()
    assert get_agent_module_spec("context_recovery") is not None


@pytest.mark.asyncio
async def test_website_change_module_detects_change(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "elyan_data"
    monkeypatch.setattr(website_mod, "resolve_elyan_data_dir", lambda: data_dir)

    calls = {"count": 0}

    def _fake_fetch(url: str, timeout: float = 10.0):
        _ = (url, timeout)
        calls["count"] += 1
        if calls["count"] == 1:
            return True, "", "pricing table old"
        return True, "", "pricing table old plus new model endpoint launch"

    monkeypatch.setattr(website_mod, "_fetch_url_text", _fake_fetch)

    first = await website_mod.run_website_change_intelligence_module(
        {"tracked_urls": ["https://example.com/pricing"]}
    )
    second = await website_mod.run_website_change_intelligence_module(
        {"tracked_urls": ["https://example.com/pricing"]}
    )

    assert first["success"] is True
    assert second["success"] is True
    assert second["changed_count"] >= 1
    assert Path(second["report_path"]).exists()


@pytest.mark.asyncio
async def test_invisible_meeting_assistant_extracts_relevance_and_actions(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "elyan_data"
    meetings = data_dir / "meetings"
    meetings.mkdir(parents=True, exist_ok=True)
    meeting_file = meetings / "team_meeting_transcript.txt"
    meeting_file.write_text(
        "\n".join(
            [
                "General intro and unrelated updates",
                "Action: Emre will update scheduler endpoint by Friday",
                "AI orchestration planning details for Elyan agents",
                "Random social talk",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(meeting_mod, "resolve_elyan_data_dir", lambda: data_dir)
    result = await meeting_mod.run_invisible_meeting_assistant_module(
        {"workspace": str(tmp_path), "focus_topics": ["Elyan", "scheduler", "AI orchestration"]}
    )

    assert result["success"] is True
    assert result["meetings_analyzed"] >= 1
    assert result["irrelevant_ratio_pct"] >= 0
    assert result["action_items"]
    assert Path(result["report_path"]).exists()
