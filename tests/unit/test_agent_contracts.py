from __future__ import annotations

from pathlib import Path

import pytest

from core.pipeline import PipelineContext, StageVerify
from core.contracts.execution_result import coerce_execution_result
from core.pipeline_upgrade.contracts import (
    assign_model_roles,
    load_output_contract,
    validate_output_contract,
    validate_research_payload,
)
from core.pipeline_upgrade.verifier import verify_research_gates
from tools.file_tools import write_file
from tools.pro_workflows import create_web_project_scaffold
from tools.research_tools.advanced_research import ResearchSource, _build_research_contract_payload


class _DummyAgent:
    pass


def _sample_research_payload() -> dict:
    return {
        "query_decomposition": {"topic": "Fourier", "queries": ["Fourier definition", "Fourier applications"]},
        "claim_list": [
            {
                "claim_id": "claim_1",
                "text": "Fourier analizi periyodik sinyalleri frekans bileşenlerine ayırır.",
                "source_urls": ["https://example.edu/a", "https://example.org/b"],
                "critical": True,
                "confidence": 0.8,
            }
        ],
        "citation_map": {
            "claim_1": [
                {"url": "https://example.edu/a", "title": "A", "reliability_score": 0.9},
                {"url": "https://example.org/b", "title": "B", "reliability_score": 0.8},
            ]
        },
        "critical_claim_ids": ["claim_1"],
        "conflicts": [],
        "uncertainty_log": [],
    }


def test_load_output_contract_for_research():
    contract = load_output_contract("research")
    assert contract["contract_id"] == "research_report_v1"


def test_validate_output_contract_rejects_missing_required_fields():
    ok, errors = validate_output_contract("research", {"contract_id": "research_report_v1"})
    assert ok is False
    assert "missing:job_type" in errors


def test_assign_model_roles_promotes_critic_for_strong_tier():
    roles = assign_model_roles({"tier": "strong"})
    assert roles["router"]["tier"] == "mid"
    assert roles["critic"]["tier"] == "strong"


def test_validate_research_payload_accepts_complete_payload():
    ok, errors = validate_research_payload(_sample_research_payload())
    assert ok is True
    assert errors == []


def test_validate_research_payload_rejects_missing_dual_source_for_critical_claim():
    payload = _sample_research_payload()
    payload["claim_list"][0]["source_urls"] = ["https://example.edu/a"]
    payload["citation_map"]["claim_1"] = [{"url": "https://example.edu/a", "title": "A", "reliability_score": 0.9}]
    ok, errors = validate_research_payload(payload)
    assert ok is False
    assert "critical_sources:claim_1" in errors


def test_verify_research_gates_fails_without_structured_payload():
    result = verify_research_gates(
        final_response="Iddia var. Belirsizlik de var.",
        source_urls=["https://example.edu/a"],
        research_payload={"claim_list": []},
    )
    assert result["ok"] is False
    assert any(item.startswith("payload:") for item in result["failed"])


@pytest.mark.asyncio
async def test_write_file_returns_contract_metadata(tmp_path):
    path = tmp_path / "report.md"
    result = await write_file(str(path), "x" * 80)
    assert result["success"] is True
    assert result["bytes_written"] >= 80
    assert len(result["sha256"]) == 64
    assert result["preview_200_chars"] == "x" * 80


@pytest.mark.asyncio
async def test_create_web_project_scaffold_returns_files_and_bytes(tmp_path):
    result = await create_web_project_scaffold(
        "Demo",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="Kurumsal landing page ve iletisim formu olustur.",
    )
    assert result["success"] is True
    assert result["files_created"]
    assert result["bytes_written"] > 0


def test_build_research_contract_payload_generates_claims_and_citations():
    payload = _build_research_contract_payload(
        "Fourier analizi",
        ["Fourier analizi sinyalleri frekans bileşenlerine ayırır."],
        [
            ResearchSource(url="https://example.edu/a", title="A", snippet="", reliability_score=0.9),
            ResearchSource(url="https://example.org/b", title="B", snippet="", reliability_score=0.8),
        ],
    )
    assert payload["claim_list"]
    assert payload["citation_map"]["claim_1"]
    assert payload["query_decomposition"]["queries"]


@pytest.mark.asyncio
async def test_stage_verify_blocks_research_delivery_without_contract_payload():
    ctx = PipelineContext(user_input="Fourier'i araştır", user_id="u1", channel="cli")
    ctx.job_type = "research"
    ctx.action = "advanced_research"
    ctx.final_response = "Iddia listesi var. Belirsizlik notu da var."
    ctx.tool_results = [{"result": {"sources": [{"url": "https://example.edu/a"}]}}]
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _DummyAgent())
    assert ctx.delivery_blocked is True
    assert "research_payload" in " ".join(ctx.errors)


def test_contract_files_exist_on_disk():
    root = Path(__file__).resolve().parents[2] / "contracts"
    assert (root / "research_report.schema.json").exists()
    assert (root / "file_task.schema.json").exists()
    assert (root / "code_task.schema.json").exists()


def test_coerce_execution_result_extracts_nested_team_artifacts(tmp_path):
    report = tmp_path / "report.docx"
    report.write_text("ok", encoding="utf-8")
    image = tmp_path / "screen.png"
    image.write_text("img", encoding="utf-8")

    payload = {
        "task": "Research",
        "specialist": "researcher",
        "status": "success",
        "artifacts": [str(report)],
        "result": {
            "success": True,
            "summary": "Hazir",
            "_proof": {"screenshot": str(image)},
        },
    }

    normalized = coerce_execution_result(payload, tool="team_mode", source="pipeline")
    paths = {artifact.path for artifact in normalized.artifacts}
    assert str(report) in paths
    assert str(image) in paths
    assert normalized.status == "success"


def test_coerce_execution_result_sanitizes_errors_and_data():
    payload = {
        "status": "failed",
        "message": None,
        "errors": [None, "timeout", ""],
        "data": {"attempt": 1},
    }
    normalized = coerce_execution_result(payload, tool="screen_workflow", source="pipeline")
    assert normalized.status == "failed"
    assert normalized.message == ""
    assert normalized.errors == ["timeout"]
    assert normalized.data == {"attempt": 1}
