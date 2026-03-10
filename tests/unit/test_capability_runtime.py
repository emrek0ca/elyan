from __future__ import annotations

from pathlib import Path

from core.pipeline import PipelineContext
from core.telemetry.runtime_trace import ensure_runtime_trace, update_runtime_trace
from core.verifier import evaluate_runtime_capability


def test_evaluate_runtime_capability_file_ops_reports_exact_path_checks(tmp_path):
    target = tmp_path / "elyan-test"
    target.mkdir()

    ctx = PipelineContext(user_input="masaüstünde elyan-test klasörü oluştur", user_id="u1", channel="cli")
    ctx.action = "create_folder"
    ctx.intent = {"action": "create_folder", "params": {"path": str(target)}}
    ctx.tool_results = [{"status": "success", "result": {"path": str(target)}}]

    result = evaluate_runtime_capability(ctx)
    assert result["contract"]["target_path"] == str(target)
    assert result["verify"]["ok"] is True
    assert result["repair"]["strategy"] == "noop"


def test_evaluate_runtime_capability_screen_uses_controlled_repair():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.tool_results = [
        {
            "status": "success",
            "raw": {"ui_map": {"frontmost_app": "Safari", "running_apps": ["Safari"]}},
        }
    ]

    result = evaluate_runtime_capability(ctx)
    assert result["contract"]["capability"] == "screen"
    assert result["verify"]["ok"] is False
    assert result["repair"]["strategy"] == "controlled_screen_failure"


def test_runtime_trace_updates_required_fields():
    ctx = PipelineContext(user_input="dosya oluştur", user_id="u1", channel="cli")
    trace = ensure_runtime_trace(ctx)
    assert trace["request_id"].startswith("req_")

    update_runtime_trace(
        ctx,
        capability="file_ops",
        selected_workflow="create_folder",
        extracted_params={"path": str(Path("/tmp/elyan-test"))},
        verifier_results={"capability_runtime": {"ok": True}},
        repair_steps=["noop"],
        final_status="success",
    )

    assert ctx.telemetry["capability"] == "file_ops"
    assert ctx.telemetry["selected_workflow"] == "create_folder"
    assert ctx.telemetry["extracted_params"]["path"] == "/tmp/elyan-test"
    assert ctx.telemetry["verifier_results"]["capability_runtime"]["ok"] is True
    assert ctx.telemetry["repair_steps"] == ["noop"]
    assert ctx.telemetry["final_status"] == "success"
