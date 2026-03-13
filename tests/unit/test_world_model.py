from types import SimpleNamespace

from core.pipeline_upgrade.router import build_context_working_set
from core.world_model import WorldModel


def test_world_model_build_snapshot_uses_similar_experience(tmp_path):
    model = WorldModel(db_path=tmp_path / "world_model.db")
    model.record_experience(
        user_id="u1",
        goal="terminalden ssh root komutunu calistir",
        action="run_safe_command",
        job_type="system_automation",
        plan=[{"id": "task_1", "action": "open_app"}, {"id": "task_2", "action": "type_text"}],
        tool_calls=[{"tool": "open_app"}, {"tool": "type_text"}],
        errors=[],
        final_response="Terminal acildi.",
        verified=True,
        success_score=0.95,
        metadata={"channel": "cli"},
    )

    snapshot = model.build_snapshot(
        user_id="u1",
        query="terminalden ssh root komutunu calistir",
        goal_graph={"workflow_chain": ["system"], "constraints": {}},
        memory_results={"episodic": [], "semantic": []},
        action="run_safe_command",
        job_type="system_automation",
    )

    assert "system" in snapshot.get("domains", [])
    assert snapshot.get("similar_experiences")
    assert any("Verify frontmost app" in item for item in snapshot.get("strategy_hints", []))


def test_build_context_working_set_includes_world_snapshot_summary():
    ctx = SimpleNamespace(
        memory_context="son gorev notlari",
        goal_constraints={"requires_evidence": True},
        attachment_index=[],
        world_snapshot={
            "summary": "domains=system; strategy=Verify frontmost app and state before UI or terminal actions.",
            "strategy_hints": [
                "Verify frontmost app and state before UI or terminal actions.",
                "Use fail-fast policy for dangerous commands and blocked permissions.",
            ],
        },
    )

    text = build_context_working_set(ctx, max_chars=1600)
    assert "World:" in text
    assert "Strategies:" in text
    assert "Verify frontmost app" in text
