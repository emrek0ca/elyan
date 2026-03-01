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
