from __future__ import annotations

from core.capabilities.file_ops.workflow import evaluate_file_ops_runtime
from core.capabilities.screen_operator.workflow import evaluate_screen_operator_runtime
from core.pipeline import PipelineContext


def test_file_ops_v3_runtime_collects_manifest_and_checksums(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("merhaba dunya" * 8, encoding="utf-8")

    ctx = PipelineContext(user_input="not yaz", user_id="u1", channel="cli")
    ctx.action = "write_file"
    ctx.intent = {"action": "write_file", "params": {"path": str(target)}}
    ctx.tool_results = [{"status": "success", "result": {"path": str(target)}}]

    result = evaluate_file_ops_runtime(ctx)
    assert result["contract"]["workflow_id"] == "file_ops.runtime.v3"
    assert result["verify"]["ok"] is True
    assert result["verify"]["artifact_manifest"][0]["sha256"]


def test_screen_operator_v3_runtime_maps_summary_failure_to_failure_code():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.intent = {"action": "screen_workflow", "params": {"mode": "inspect"}}
    ctx.tool_results = [
        {
            "status": "success",
            "raw": {"ui_map": {"frontmost_app": "Safari", "running_apps": ["Safari"]}, "path": "/tmp/screen.png"},
        }
    ]

    result = evaluate_screen_operator_runtime(ctx)
    assert result["contract"]["workflow_id"] == "screen_operator.runtime.v3"
    assert result["verify"]["ok"] is False
    assert "SCREEN_SUMMARY_MISSING" in result["repair"]["failed_codes"]
    assert result["repair"]["strategy"] == "controlled_screen_failure"


def test_screen_operator_v3_control_mode_requires_after_signal():
    ctx = PipelineContext(user_input="safari ac", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.intent = {"action": "screen_workflow", "params": {"mode": "inspect_and_control"}}
    ctx.tool_results = [
        {
            "status": "success",
            "result": {
                "summary": "Safari acildi",
                "screenshots": ["/tmp/before.png"],
                "ui_map": {"frontmost_app": "Safari"},
                "control": {"steps_executed": 1},
            },
        }
    ]

    result = evaluate_screen_operator_runtime(ctx)
    assert result["verify"]["ok"] is False
    assert "NO_VISUAL_CHANGE" in result["verify"]["failed_codes"]
