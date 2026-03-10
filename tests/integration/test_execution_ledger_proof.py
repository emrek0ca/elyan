import json
from pathlib import Path

from core.evidence.execution_ledger import ExecutionLedger


def test_execution_ledger_manifest_contains_hashes(tmp_path):
    out = tmp_path / "result.txt"
    out.write_text("hello", encoding="utf-8")

    ledger = ExecutionLedger(run_id="test_ledger_001")
    ledger.log_step(
        step="write",
        tool="write_file",
        status="success",
        input_payload={"x": 1},
        params={"path": str(out)},
        result={"success": True, "path": str(out)},
        duration_ms=12,
    )
    manifest_path = ledger.write_manifest(status="success")

    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["steps"]
    assert payload["artifacts"]
    assert payload["artifacts"][0]["sha256"]


def test_execution_ledger_registers_nested_team_artifacts(tmp_path):
    doc = tmp_path / "team_report.md"
    doc.write_text("report", encoding="utf-8")
    shot = tmp_path / "proof.png"
    shot.write_text("png", encoding="utf-8")

    ledger = ExecutionLedger(run_id="test_team_artifacts_001")
    ledger.register_result(
        tool="team_mode",
        source="pipeline",
        result={
            "task": "Research",
            "specialist": "researcher",
            "status": "success",
            "artifacts": [str(doc)],
            "result": {
                "success": True,
                "summary": "done",
                "_proof": {"screenshot": str(shot)},
            },
        },
    )

    paths = {item["path"] for item in ledger.artifacts}
    assert str(doc.resolve()) in paths
    assert str(shot.resolve()) in paths


def test_execution_ledger_respects_proofs_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_PROOFS_DIR", str(tmp_path / "proofs"))
    ledger = ExecutionLedger(run_id="test_env_root_001")
    assert str(ledger.base_dir).startswith(str((tmp_path / "proofs").resolve()))


def test_execution_ledger_emits_tool_started_and_finished_events(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_PROOFS_DIR", str(tmp_path / "proofs"))
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))

    out = tmp_path / "result.txt"
    out.write_text("hello", encoding="utf-8")

    ledger = ExecutionLedger(run_id="test_tool_event_001")
    ledger.log_step(
        step="write",
        tool="write_file",
        status="success",
        input_payload={"x": 1},
        params={"path": str(out)},
        result={"success": True, "path": str(out)},
        duration_ms=18,
    )

    trace_path = tmp_path / "runs" / "test_tool_event_001" / "trace.jsonl"
    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["event"] for row in lines] == ["tool.started", "tool.finished"]
    assert lines[0]["tool_name"] == "write_file"
    assert lines[0]["status"] == "started"
    assert lines[1]["tool_name"] == "write_file"
    assert lines[1]["latency_ms"] == 18
