from __future__ import annotations

from pathlib import Path

from runtime.desktop_work_order import canonical_capability, validate_payload, verify_result
from runtime import bridge


def _work_order(*, require_artifact: bool = False) -> dict:
    outputs = [{"kind": "chat_result", "format": "elyan_blocks.v2", "required": True}]
    if require_artifact:
        outputs.append({"kind": "artifact", "format": "artifact_reference", "required": True})
    return {
        "schema": "elyan.desktop_work_order.v1",
        "source": "mobile_chat_dispatch",
        "goal": {
            "kind": "document_task",
            "summary": "Tipli belge görevi",
            "language": "tr",
            "sourceTextHash": "a" * 24,
        },
        "entities": [],
        "constraints": [],
        "requiredCapabilities": ["filesystem_write"],
        "localContextNeeded": ["filesystem"],
        "expectedOutputs": outputs,
        "verificationRules": [
            {"id": "runtime_completed", "description": "Runtime tamamlandı.", "evidence": "runtime_status"},
            {"id": "tool_result", "description": "Araç sonucu var.", "evidence": "tool_result"},
            {"id": "artifact", "description": "Artifact varsa doğrulanır.", "evidence": "artifact"},
        ],
        "execution": {"mode": "cowork_dispatch", "approvalPolicy": "capability_policy", "maxSteps": 8},
        "planPreview": {
            "summary": "Tipli belge görevi",
            "privacyClass": "local_private",
            "steps": [
                {
                    "id": "step_write",
                    "capability": "document.write",
                    "description": "Belge yazılacak.",
                    "args": {"title": "Rapor", "sourceContext": "Tipli içerik"},
                }
            ],
        },
    }


def test_work_order_validation_normalizes_capabilities() -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order()})

    assert validation.ok is True
    assert validation.work_order is not None
    assert validation.work_order["requiredCapabilities"] == ["document_write"]
    assert validation.work_order["planPreview"]["steps"][0]["capability"] == "document_write"
    assert canonical_capability("screen_context") == "desktop_operator.observe_screen"


def test_work_order_validation_preserves_additive_runtime_quality_metadata() -> None:
    work_order = _work_order()
    work_order["contextPack"] = {
        "sourceReference": "latest_artifact",
        "conversationState": {"turnKind": "correction", "carryForward": True},
        "latestArtifactRef": {"id": "artifact_1", "kind": "image", "summary": "Beyaz kedi"},
    }
    work_order["executionPlan"] = {
        "mode": "data_workflow",
        "planner": "server_brain",
        "allowReplan": True,
    }
    work_order["permissionEnvelope"] = {
        "mode": "single_full_access_surface",
        "coveredPermissions": ["browser_control", "computer_control"],
        "separateApprovalFor": ["delete", "overwrite", "send_email"],
        "ttlSeconds": 900,
    }

    validation = validate_payload({"desktopWorkOrder": work_order})

    assert validation.ok is True
    assert validation.work_order is not None
    assert validation.work_order["contextPack"]["sourceReference"] == "latest_artifact"
    assert validation.work_order["contextPack"]["conversationState"]["turnKind"] == "correction"
    assert validation.work_order["permissionEnvelope"]["mode"] == "single_full_access_surface"


def test_work_order_validation_rejects_unknown_schema() -> None:
    work_order = _work_order()
    work_order["schema"] = "elyan.desktop_work_order.v999"

    validation = validate_payload({"desktopWorkOrder": work_order})

    assert validation.ok is False
    assert validation.errors[0]["code"] == "WORK_ORDER_SCHEMA_UNSUPPORTED"


def test_work_order_verification_blocks_completion_without_required_artifact() -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order(require_artifact=True)})
    assert validation.work_order is not None

    result = verify_result(
        validation.work_order,
        {
            "chatOk": True,
            "assistantMessage": "Dosya hazır.",
            "toolEvents": [{"tool": "document_write", "ok": True}],
            "structuredResult": {"created": True},
            "artifacts": [],
        },
    )

    assert result["passed"] is False
    assert "output:artifact" in result["missingEvidence"]


def test_work_order_verification_accepts_tool_and_artifact_evidence(tmp_path: Path) -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order(require_artifact=True)})
    assert validation.work_order is not None
    artifact_path = tmp_path / "report.docx"
    artifact_path.write_bytes(b"verified artifact")

    result = verify_result(
        validation.work_order,
        {
            "chatOk": True,
            "assistantMessage": "Dosya hazır.",
            "toolEvents": [{"tool": "document_write", "ok": True}],
            "structuredResult": {"created": True},
            "artifacts": [{"path": str(artifact_path), "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}],
        },
    )

    assert result["passed"] is True
    assert result["status"] == "passed"


def test_work_order_verification_accepts_verified_image_fetch_as_file_update(tmp_path: Path) -> None:
    work_order = _work_order(require_artifact=True)
    work_order["expectedOutputs"].append(
        {"kind": "file_update", "format": "state_readback", "required": True}
    )
    validation = validate_payload({"desktopWorkOrder": work_order})
    assert validation.work_order is not None
    artifact_path = tmp_path / "kedi.jpg"
    artifact_path.write_bytes(b"verified image")

    result = verify_result(
        validation.work_order,
        {
            "chatOk": True,
            "assistantMessage": "Görsel kaydedildi.",
            "toolEvents": [{"tool": "image_fetch", "ok": True}],
            "structuredResult": {"kind": "image_fetch", "savedCount": 1},
            "artifacts": [{"path": str(artifact_path), "contentType": "image/jpeg"}],
        },
    )

    assert result["passed"] is True
    assert "output:file_update" not in result["missingEvidence"]


def test_work_order_verification_rejects_failed_tool_and_unverified_artifact(tmp_path: Path) -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order(require_artifact=True)})
    assert validation.work_order is not None

    result = verify_result(
        validation.work_order,
        {
            "chatOk": True,
            "assistantMessage": "Dosya hazır.",
            "toolEvents": [{"tool": "document_write", "ok": False, "errorCode": "WRITE_FAILED"}],
            "structuredResult": {"created": True},
            "artifacts": [{"path": str(tmp_path / "missing.docx")}],
        },
    )

    assert result["passed"] is False
    assert result["evidenceCounts"] == {"toolResults": 0, "artifacts": 0, "structuredResults": 1, "stateReadbacks": 0}
    assert "output:artifact" in result["missingEvidence"]
    assert "rule:tool_result" in result["missingEvidence"]


def test_work_order_verification_requires_explicit_runtime_success() -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order()})
    assert validation.work_order is not None

    result = verify_result(
        validation.work_order,
        {
            "assistantMessage": "Bitti.",
            "toolEvents": [{"tool": "document_write", "ok": True}],
            "structuredResult": {"created": True},
            "artifacts": [],
        },
    )

    assert result["passed"] is False
    assert "output:chat_result" in result["missingEvidence"]
    assert "rule:runtime_completed" in result["missingEvidence"]


def test_work_order_verification_allows_completed_chat_only_runtime_without_tool_event() -> None:
    validation = validate_payload({"desktopWorkOrder": _work_order()})
    assert validation.work_order is not None

    result = verify_result(
        validation.work_order,
        {
            "chatOk": True,
            "assistantMessage": "Görev tamamlandı.",
            "toolEvents": [],
            "executionTrace": {"status": "completed"},
        },
    )

    assert result["passed"] is True
    assert result["evidenceFallbacks"] == [
        {
            "kind": "tool_result",
            "source": "runtime_status",
            "reason": "chat_only_runtime_completion",
        }
    ]


def test_runtime_public_payload_hides_private_paths_and_content() -> None:
    runtime = object.__new__(bridge.RuntimeBridge)

    artifact = runtime._public_runtime_artifact(
        {
            "kind": "file",
            "path": "/Users/example/private/report.docx",
            "sourcePath": "/Users/example/private/source.pdf",
            "textContent": "private document content",
            "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
    )
    structured = runtime._public_runtime_structured_result(
        {
            "kind": "document_write",
            "created": True,
            "outputPath": "/Users/example/private/report.docx",
            "sourceContext": "private document content",
            "summary": "Belge üretildi.",
        }
    )

    assert artifact["name"] == "report.docx"
    assert artifact["localRef"].startswith("local_")
    assert "path" not in artifact
    assert "sourcePath" not in artifact
    assert "textContent" not in artifact
    assert structured == {"kind": "document_write", "created": True, "summary": "Belge üretildi."}


def test_state_readback_counts_as_evidence_for_verified_side_effect() -> None:
    """Kapatma teyitli (closed_confirmed) bir yan etki state_readback kanıtı
    sayılır ve görev geçer."""
    work_order = _work_order()
    result = verify_result(
        work_order,
        {
            "chatOk": True,
            "assistantMessage": "Chrome kapatıldı.",
            "toolEvents": [
                {
                    "tool": "close_app",
                    "ok": True,
                    "verified": True,
                    "stateReadback": {"observed": True, "status": "closed_confirmed"},
                }
            ],
        },
    )
    assert result["passed"] is True
    assert result["evidenceCounts"]["stateReadbacks"] == 1


def test_unverified_side_effect_fails_completion() -> None:
    """Adım 'yaptım' (ok) deyip etkisini kanıtlayamazsa (observed=False) görev
    tamamlandı sayılmaz — 'prove it' dürüstlük kapısı."""
    work_order = _work_order()
    result = verify_result(
        work_order,
        {
            "chatOk": True,
            "assistantMessage": "Chrome kapatıldı.",
            "toolEvents": [
                {
                    "tool": "close_app",
                    "ok": True,
                    "verified": False,
                    "stateReadback": {"observed": False, "status": "close_unconfirmed"},
                }
            ],
        },
    )
    assert result["passed"] is False
    assert result["unverifiedSideEffects"] == ["close_app"]
    assert "sideeffect:close_app" in result["missingEvidence"]
