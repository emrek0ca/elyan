from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runtime.emre_workflows import (
    list_emre_workflow_reports,
    load_latest_benchmark_summary,
    run_emre_workflow_preset,
)


class _Planner:
    async def start_request(self, request: str, *, clear_live_state: bool = False):
        assert request
        assert clear_live_state is True
        return {
            "success": True,
            "status": "completed",
            "task_id": "task-demo",
            "plan": {
                "name": "demo-plan",
                "goal": request,
                "steps": [{"kind": "screen", "name": "step_1"}],
            },
            "planning_trace": {"matched_rules": ["demo"]},
            "comparison": {
                "planned_step_count": 1,
                "completed_step_count": 1,
                "steps": [{"name": "step_1", "status": "completed"}],
            },
            "task_result": {
                "task_state": {"retry_counts": {"1": 1}, "replan_count": 1},
                "artifacts": [{"path": str(Path("/tmp/demo.png")), "type": "image"}],
            },
        }


@pytest.mark.asyncio
async def test_run_emre_workflow_preset_persists_report(tmp_path: Path):
    report = await run_emre_workflow_preset(
        "telegram_desktop_task_completion",
        planner=_Planner(),
        reports_root=tmp_path,
        clear_live_state=True,
    )

    assert report["success"] is True
    workflow = report["workflow"]
    assert workflow["workflow_name"] == "Telegram-triggered desktop task completion"
    assert workflow["completed_steps"] == 1
    assert workflow["retry_count"] == 1
    assert workflow["replan_count"] == 1
    assert Path(report["report_root"]).exists()
    assert (Path(report["report_root"]) / "report.json").exists()
    assert (Path(report["report_root"]) / "report.md").exists()


def test_load_latest_benchmark_summary_and_report_listing(tmp_path: Path):
    reports_root = tmp_path / "workflows" / "preset_runs" / "123_demo"
    reports_root.mkdir(parents=True)
    (reports_root / "report.json").write_text(
        json.dumps(
            {
                "name": "telegram_desktop_task_completion",
                "workflow_name": "Telegram-triggered desktop task completion",
                "status": "completed",
                "task_id": "task-demo",
                "completed_steps": 2,
                "planned_steps": 2,
                "completed_step_names": ["open_safari", "click_continue"],
                "retry_count": 0,
                "replan_count": 0,
                "failure_code": "",
                "summary": "completed",
                "artifacts": [],
                "screenshots": [],
            }
        ),
        encoding="utf-8",
    )

    benchmark_root = tmp_path / "benchmarks" / "111"
    benchmark_root.mkdir(parents=True)
    (benchmark_root / "summary.json").write_text(
        json.dumps(
            {
                "pass_count": 20,
                "total": 20,
                "average_retries": 0.1,
                "average_replans": 0.5,
                "failure_reasons": {},
            }
        ),
        encoding="utf-8",
    )

    reports = list_emre_workflow_reports(reports_root=tmp_path / "workflows", limit=5)
    summary = load_latest_benchmark_summary(reports_roots=[tmp_path / "benchmarks"])

    assert reports[0]["workflow_name"] == "Telegram-triggered desktop task completion"
    assert reports[0]["completed_step_names"] == ["open_safari", "click_continue"]
    assert summary["pass_count"] == 20
    assert summary["remaining_failure_codes"] == []
