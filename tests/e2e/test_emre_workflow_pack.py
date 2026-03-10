from __future__ import annotations

from pathlib import Path

import pytest

from core.runtime import EMRE_WORKFLOW_PRESETS, run_emre_workflow_pack
from tests.e2e.test_production_path_reliability import _benchmark_cases


@pytest.mark.asyncio
async def test_emre_workflow_pack_runs_presets_and_persists_reports(tmp_path: Path):
    report = await run_emre_workflow_pack(_benchmark_cases(tmp_path / "workspace"), reports_root=tmp_path / "reports")

    assert report["success"] is True
    summary = report["summary"]
    assert summary["pass_count"] == len(EMRE_WORKFLOW_PRESETS)
    assert summary["total"] == len(EMRE_WORKFLOW_PRESETS)
    assert {row["name"] for row in summary["rows"]} == {item["name"] for item in EMRE_WORKFLOW_PRESETS}
    for row in summary["rows"]:
        assert isinstance(row.get("workflow_name"), str) and row["workflow_name"]
        assert isinstance(row.get("completed_steps"), list)
        assert "retry_count" in row
        assert "replan_count" in row
        assert "final_status" in row
        assert "failure_code" in row
    for artifact in report["artifacts"]:
        assert Path(str(artifact["path"])).exists()
