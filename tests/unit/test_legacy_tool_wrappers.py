from __future__ import annotations

import inspect

import pytest

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload, wrap_legacy_tool
from tools import AVAILABLE_TOOLS


@pytest.mark.asyncio
async def test_wrap_legacy_tool_fails_deterministically_for_none():
    async def _legacy_none():
        return None

    wrapped = wrap_legacy_tool("legacy_none", _legacy_none)
    result = await wrapped()

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert result["artifacts"] == []
    assert result["evidence"][0]["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert result["errors"] == ["TOOL_CONTRACT_VIOLATION"]
    assert result["metrics"]["wrapper_source"] == "legacy_tool_wrapper"


@pytest.mark.asyncio
async def test_wrap_legacy_tool_fails_for_ambiguous_success_dict():
    async def _legacy_ambiguous():
        return {"success": True}

    wrapped = wrap_legacy_tool("legacy_ambiguous", _legacy_ambiguous)
    result = await wrapped()

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert "ambiguous success payload" in result["error"]


def test_wrap_legacy_tool_normalizes_string_output_and_preserves_signature():
    def _legacy_string(path: str, content: str) -> str:
        return f"saved {path}: {content}"

    wrapped = wrap_legacy_tool("legacy_string", _legacy_string)
    result = wrapped("/tmp/x.txt", "ok")

    assert list(inspect.signature(wrapped).parameters) == ["path", "content"]
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["message"] == "saved /tmp/x.txt: ok"
    assert result["output"] == "saved /tmp/x.txt: ok"
    assert isinstance(result["artifact_manifest"], list)


def test_normalize_legacy_tool_payload_preserves_raw_artifacts_and_adds_contract_fields(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("ok", encoding="utf-8")
    payload = normalize_legacy_tool_payload(
        {
            "success": True,
            "artifacts": [str(report)],
            "duration_ms": 42,
            "citation_map": {"claim_1": [{"url": "https://example.com"}]},
            "source_urls": ["https://example.com"],
        },
        tool="legacy_report",
    )

    assert payload["success"] is True
    assert payload["status"] == "success"
    assert payload["artifacts"] == [str(report)]
    assert payload["artifact_manifest"][0]["path"] == str(report)
    assert payload["metrics"]["duration_ms"] == 42
    assert payload["evidence"]
    assert payload["_tool_result"]["tool"] == "legacy_report"


@pytest.mark.asyncio
async def test_available_tools_write_file_surface_is_normalized(tmp_path):
    tool = AVAILABLE_TOOLS.get("write_file")
    assert callable(tool)

    target = tmp_path / "note.md"
    result = await tool(str(target), "x" * 80)

    assert result["success"] is True
    assert result["status"] == "success"
    assert isinstance(result["artifact_manifest"], list) and result["artifact_manifest"]
    assert result["artifact_manifest"][0]["path"] == str(target)
    assert result["_tool_result"]["status"] == "success"
    assert result["metrics"]["wrapper_source"] == "legacy_tool_wrapper"
