from __future__ import annotations

from pathlib import Path

import pytest

from core.pipeline import PipelineContext, StageVerify
from core.contracts.execution_result import coerce_execution_result
from core.contracts.tool_result import coerce_tool_result
from core.pipeline_upgrade.contracts import (
    assign_model_roles,
    load_output_contract,
    validate_output_contract,
    validate_research_payload,
)
from core.pipeline_upgrade.verifier import verify_research_gates
from tools.file_tools import copy_file, list_files, move_file, read_file, rename_file, search_files, write_file
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
    assert result["status"] == "success"
    assert result["bytes_written"] >= 80
    assert len(result["sha256"]) == 64
    assert result["preview_200_chars"] == "x" * 80
    assert str(result["output_path"]).endswith("report.md")
    assert result["artifacts"]


@pytest.mark.asyncio
async def test_list_files_returns_standardized_payload_and_coerces(tmp_path):
    sample = tmp_path / "note.txt"
    sample.write_text("ok", encoding="utf-8")

    result = await list_files(str(tmp_path))
    normalized = coerce_tool_result(result, tool="list_files")

    assert result["success"] is True
    assert result["status"] == "success"
    assert str(result["output_path"]).endswith(tmp_path.name)
    assert result["artifacts"][0]["type"] == "directory"
    assert result["count"] == 1
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0]["name"] == "note.txt"
    assert normalized.status == "success"
    assert normalized.artifacts[0].type == "directory"
    assert normalized.artifacts[0].path == str(tmp_path)


@pytest.mark.asyncio
async def test_read_file_returns_standardized_payload_and_coerces(tmp_path):
    sample = tmp_path / "note.txt"
    sample.write_text("merhaba dunya", encoding="utf-8")

    result = await read_file(str(sample))
    normalized = coerce_tool_result(result, tool="read_file")

    assert result["success"] is True
    assert result["status"] == "success"
    assert str(result["output_path"]).endswith("note.txt")
    assert result["content"] == "merhaba dunya"
    assert result["data"]["content"] == "merhaba dunya"
    assert result["bytes_read"] == len("merhaba dunya")
    assert result["artifacts"][0]["type"] == "text"
    assert normalized.status == "success"
    assert normalized.artifacts[0].type == "text"
    assert normalized.artifacts[0].path == str(sample)


@pytest.mark.asyncio
async def test_search_files_returns_sorted_standardized_payload(tmp_path):
    a = tmp_path / "b_note.txt"
    b = tmp_path / "a_note.txt"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")

    result = await search_files("*.txt", str(tmp_path))
    normalized = coerce_tool_result(result, tool="search_files")

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["matches"] == sorted(result["matches"])
    assert result["data"]["count"] == 2
    assert normalized.status == "success"
    assert normalized.artifacts[0].type == "directory"


@pytest.mark.asyncio
async def test_move_file_returns_verified_standardized_payload(tmp_path):
    source = tmp_path / "from.txt"
    target_dir = tmp_path / "dest"
    target_dir.mkdir()
    source.write_text("icerik", encoding="utf-8")

    result = await move_file(str(source), str(target_dir))
    normalized = coerce_tool_result(result, tool="move_file")

    moved_path = target_dir / "from.txt"
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["destination"] == str(moved_path)
    assert result["data"]["moved"] is True
    assert moved_path.exists()
    assert not source.exists()
    assert normalized.status == "success"
    assert normalized.artifacts[0].path == str(moved_path)


@pytest.mark.asyncio
async def test_copy_file_returns_verified_standardized_payload(tmp_path):
    source = tmp_path / "from.txt"
    target_dir = tmp_path / "dest"
    target_dir.mkdir()
    source.write_text("icerik", encoding="utf-8")

    result = await copy_file(str(source), str(target_dir))
    normalized = coerce_tool_result(result, tool="copy_file")

    copied_path = target_dir / "from.txt"
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["destination"] == str(copied_path)
    assert result["data"]["copied"] is True
    assert copied_path.exists()
    assert source.exists()
    assert normalized.status == "success"
    assert normalized.artifacts[0].path == str(copied_path)


@pytest.mark.asyncio
async def test_rename_file_returns_verified_standardized_payload(tmp_path):
    source = tmp_path / "old.txt"
    source.write_text("icerik", encoding="utf-8")

    result = await rename_file(str(source), "new.txt")
    normalized = coerce_tool_result(result, tool="rename_file")

    renamed_path = tmp_path / "new.txt"
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["new_name"] == "new.txt"
    assert result["data"]["renamed"] is True
    assert renamed_path.exists()
    assert not source.exists()
    assert normalized.status == "success"
    assert normalized.artifacts[0].path == str(renamed_path)


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
