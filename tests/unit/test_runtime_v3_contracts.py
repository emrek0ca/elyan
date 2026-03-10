from __future__ import annotations

import json
from pathlib import Path

from core.contracts.delivery_envelope import DeliveryAttachment, DeliveryEnvelope
from core.contracts.execution_plan import ExecutionPlan, PlanCondition, PlanStep
from core.contracts.failure_taxonomy import FailureCode
from core.contracts.operator_request import CapabilitySelection, OperatorAttachment, OperatorRequest
from core.contracts.tool_result import coerce_tool_result
from core.telemetry.events import TelemetryEvent
from core.telemetry.run_store import TelemetryRunStore


def test_operator_request_and_selection_contracts_roundtrip():
    request = OperatorRequest(
        request_id="req_1",
        host="desktop",
        channel="cli",
        user_id="u1",
        machine_id="m1",
        input_text="ekrana bak",
        attachments=[OperatorAttachment(path="/tmp/a.png", type="image")],
    )
    selection = CapabilitySelection(
        capability="screen_operator",
        workflow_id="screen_operator.runtime.v3",
        confidence=0.93,
        extracted_params={"mode": "inspect"},
        routing_reason="explicit screen keywords",
    )
    assert request.to_dict()["attachments"][0]["type"] == "image"
    assert selection.to_dict()["workflow_id"] == "screen_operator.runtime.v3"


def test_execution_plan_to_dict_contains_policies():
    plan = ExecutionPlan(
        request_id="req_2",
        workflow_path=["understand", "plan", "execute"],
        steps=[
            PlanStep(
                step_id="s1",
                capability="file_ops",
                action="write_file",
                params={"path": "/tmp/note.txt"},
                preconditions=[PlanCondition(code="path_allowed")],
                postconditions=[PlanCondition(code="non_empty")],
                timeout_ms=5000,
                repair_policy={"code": FailureCode.EMPTY_FILE_OUTPUT.value},
                verify_policy={"gate": "file_non_empty"},
            )
        ],
    )
    payload = plan.to_dict()
    assert payload["steps"][0]["repair_policy"]["code"] == FailureCode.EMPTY_FILE_OUTPUT.value
    assert payload["steps"][0]["postconditions"][0]["code"] == "non_empty"


def test_coerce_tool_result_rejects_none_and_ambiguous_success():
    none_result = coerce_tool_result(None, tool="legacy_tool")
    assert none_result.status == "failed"
    assert FailureCode.TOOL_CONTRACT_VIOLATION.value in none_result.errors

    ambiguous = coerce_tool_result({}, tool="legacy_tool")
    assert ambiguous.status == "failed"
    assert ambiguous.data["error_code"] == FailureCode.TOOL_CONTRACT_VIOLATION.value


def test_delivery_envelope_to_dict():
    envelope = DeliveryEnvelope(
        status="success",
        text_summary="Hazir",
        attachments=[DeliveryAttachment(path="/tmp/report.md", type="text")],
        artifact_manifest=[{"path": "/tmp/report.md"}],
    )
    assert envelope.to_dict()["attachments"][0]["path"] == "/tmp/report.md"


def test_telemetry_run_store_writes_phase1_files(tmp_path, monkeypatch):
    monkeypatch.setattr("core.telemetry.run_store.resolve_runs_root", lambda: tmp_path / "runs")
    store = TelemetryRunStore("run_v3_001")
    store.record_event(
        TelemetryEvent(
            event="run.started",
            request_id="run_v3_001",
            selected_capability="file_ops",
            workflow_path=["understand", "plan"],
            extracted_params={"path": "/tmp/x.txt"},
        )
    )
    store.write_summary({"status": "success", "selected_capability": "file_ops"})
    store.write_verification({"status": "success", "checks": []})
    store.write_delivery({"status": "success", "text_summary": "ok"})
    store.write_artifact_manifest([{"path": "/tmp/x.txt"}])

    run_dir = tmp_path / "runs" / "run_v3_001"
    assert (run_dir / "trace.jsonl").exists()
    assert json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["status"] == "success"
    assert json.loads((run_dir / "verification.json").read_text(encoding="utf-8"))["status"] == "success"
    assert json.loads((run_dir / "delivery.json").read_text(encoding="utf-8"))["text_summary"] == "ok"
    assert json.loads((run_dir / "artifacts" / "manifest.json").read_text(encoding="utf-8"))["artifacts"][0]["path"] == "/tmp/x.txt"
