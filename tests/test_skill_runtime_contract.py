from __future__ import annotations

from pathlib import Path

import pytest

from runtime import bridge, mcp_runtime, skill_runtime, state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path / "state")
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "state" / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")
    monkeypatch.chdir(tmp_path)


def _write_fixture_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fixture_mcp_server.py"
    server_path.write_text(
        """
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("Fixture Server")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo_readonly(text: str) -> dict[str, str]:
    return {"echo": text}


@mcp.tool()
def write_note(path: str, text: str) -> dict[str, str]:
    target = Path(path)
    target.write_text(text, encoding="utf-8")
    return {"outputPath": str(target), "result": "written"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
        """.strip(),
        encoding="utf-8",
    )
    return server_path


def _configured_mcp_state(tmp_path: Path, server_path: Path) -> dict[str, object]:
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_fixture",
            "name": "fixture",
            "transport": "stdio",
            "command": "python3",
            "args": [str(server_path)],
            "cwd": str(tmp_path),
            "enabled": True,
            "startupTimeoutSec": 15,
            "callTimeoutSec": 30,
        }
    ]
    return state_store.save_state(state)


def test_skill_refresh_lists_builtin_manifests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)

    status = skill_runtime.refresh_skill_runtime()

    assert status["available"] is True
    assert status["manifestCount"] >= 10
    assert status["activeSkillCount"] >= 8
    assert any(item["id"] == "document.summary" for item in status["skills"])
    assert any(item["id"] == "research.brief" for item in status["skills"])
    assert any(item["id"] == "document.report_from_context" for item in status["skills"])
    assert any(item["id"] == "source.verify" for item in status["skills"])
    assert any(item["id"] == "workspace.answer" for item in status["skills"])
    assert any(item["id"] == "file.explain" for item in status["skills"])


def test_skill_refresh_fails_closed_for_invalid_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    skills_root = state_store.CONFIG_DIR.parent / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / "broken.json").write_text("{not-json", encoding="utf-8")

    status = skill_runtime.refresh_skill_runtime()

    assert status["lastErrorCode"] == "SKILL_MANIFEST_INVALID"


def test_skill_run_executes_document_summary_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("Elyan local runtime test belgesi.", encoding="utf-8")
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_skill_summary",
            "taskId": "task_skill_summary",
            "capability": "skill.run",
            "payload": {
                "skillId": "document.summary",
                "payload": {"path": str(source)},
            },
        }
    )

    assert response["ok"] is True
    result = response["result"]
    assert result["ok"] is True
    assert result["result"]["result"]["kind"] == "run_skill"
    assert "Elyan local runtime test belgesi." in result["result"]["output"]


def test_skill_run_executes_research_brief_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    source = tmp_path / "research-notes.txt"
    source.write_text("Elyan capability cohesion sprint notes.", encoding="utf-8")
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_skill_research_brief",
            "taskId": "task_skill_research_brief",
            "capability": "skill.run",
            "payload": {
                "skillId": "research.brief",
                "payload": {
                    "query": "Elyan capability cohesion sprint",
                    "sources": "workspace",
                    "limit": 4,
                },
            },
        }
    )

    assert response["ok"] is True
    result = response["result"]
    assert result["ok"] is True
    assert result["result"]["result"]["kind"] == "run_skill"
    assert result["result"]["result"]["lastStepResult"]["kind"] == "retrieve_context"
    assert "Bağlam eşleşmeleri" in result["result"]["output"] or "İlgili yerel bağlam" in result["result"]["output"]


def test_skill_run_executes_source_verify_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    source = tmp_path / "research-notes.txt"
    source.write_text("Elyan source verification notes.", encoding="utf-8")
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_skill_source_verify",
            "taskId": "task_skill_source_verify",
            "capability": "skill.run",
            "payload": {
                "skillId": "source.verify",
                "payload": {
                    "query": "Elyan source verification notes",
                    "sources": "workspace",
                    "limit": 4,
                },
            },
        }
    )

    assert response["ok"] is True
    result = response["result"]
    assert result["ok"] is True
    assert result["result"]["result"]["kind"] == "run_skill"
    assert result["result"]["result"]["lastStepResult"]["kind"] == "retrieve_context"


def test_skill_run_executes_context_report_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    source = tmp_path / "report-source.txt"
    source.write_text("Elyan report generation source context.", encoding="utf-8")
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_skill_report",
            "taskId": "task_skill_report",
            "capability": "skill.run",
            "payload": {
                "skillId": "document.report_from_context",
                "payload": {
                    "query": "Elyan report generation source context",
                    "outputPath": "reports/elyan-report.docx",
                    "title": "Elyan Report",
                    "sources": "workspace",
                    "limit": 4,
                },
                "_confirmed": True,
            },
        }
    )

    assert response["ok"] is True
    result = response["result"]
    assert result["ok"] is True
    assert result["result"]["result"]["kind"] == "run_skill"
    assert result["result"]["result"]["lastStepResult"]["kind"] == "document_write"
    assert "Bağlam eşleşmeleri" in result["result"]["output"] or "DOCX oluşturuldu" in result["result"]["output"]
    assert "Bağlam eşleşmeleri" in result["result"]["result"]["lastStepResult"]["sourceContext"]
    assert (tmp_path / "reports" / "elyan-report.docx").exists()


def test_skill_run_requires_confirmation_for_docx_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()

    denied = runtime.handle(
        {
            "id": "req_skill_docx_denied",
            "taskId": "task_skill_docx_denied",
            "capability": "skill.run",
            "payload": {
                "skillId": "document.docx_from_context",
                "payload": {
                    "prompt": "Elyan test belgesi",
                    "outputPath": "elyan.docx",
                },
            },
        }
    )
    allowed = runtime.handle(
        {
            "id": "req_skill_docx_allowed",
            "taskId": "task_skill_docx_allowed",
            "capability": "skill.run",
            "payload": {
                "skillId": "document.docx_from_context",
                "payload": {
                    "prompt": "Elyan test belgesi",
                    "outputPath": "elyan.docx",
                },
                "_confirmed": True,
            },
        }
    )

    assert denied["ok"] is False
    assert denied["error"]["code"] == "PERMISSION_REQUIRED"
    assert allowed["ok"] is True
    artifacts = allowed["result"]["artifacts"]
    assert artifacts[0]["name"] == "elyan.docx"
    assert (tmp_path / "elyan.docx").exists()


def test_skill_refresh_marks_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)

    def fake_dependency_status(capability: str) -> dict[str, object]:
        if capability == "document_write":
            return {
                "capability": capability,
                "available": False,
                "lastErrorCode": "DEPENDENCY_UNAVAILABLE",
                "lastErrorMessage": "Document writer missing.",
            }
        return {
            "capability": capability,
            "available": True,
            "lastErrorCode": "",
            "lastErrorMessage": "",
        }

    monkeypatch.setattr(skill_runtime, "capability_dependency_status", fake_dependency_status)

    status = skill_runtime.refresh_skill_runtime()
    report_skill = next(
        item for item in status["skills"] if item["id"] == "document.report_from_context"
    )

    assert report_skill["available"] is False
    assert report_skill["lastErrorCode"] == "DEPENDENCY_UNAVAILABLE"
    assert report_skill["dependencySummary"]["blockedCapabilities"] == ["document_write"]
    assert report_skill["dependencySummary"]["blockedSteps"] >= 1
    assert status["lastErrorCode"] == "DEPENDENCY_UNAVAILABLE"
    assert status["blockedSkillCount"] >= 1
    assert status["readySkillCount"] >= 1

    runtime = bridge.RuntimeBridge()
    failed = runtime.handle(
        {
            "id": "req_skill_report_unavailable",
            "taskId": "task_skill_report_unavailable",
            "capability": "skill.run",
            "payload": {
                "skillId": "document.report_from_context",
                "payload": {
                    "query": "Elyan report generation source context",
                    "outputPath": "reports/elyan-report.docx",
                    "title": "Elyan Report",
                    "sources": "workspace",
                },
                "_confirmed": True,
            },
        }
    )

    assert failed["ok"] is False
    assert failed["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_skill_run_allows_only_readonly_mcp_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_mcp_state(tmp_path, server_path)
    mcp_runtime.refresh_mcp_runtime(saved)
    runtime = bridge.RuntimeBridge()

    allowed = runtime.handle(
        {
            "id": "req_skill_mcp_allowed",
            "taskId": "task_skill_mcp_allowed",
            "capability": "skill.run",
            "payload": {
                "skillId": "mcp.readonly_tool_proxy",
                "payload": {
                    "serverId": "mcp_fixture",
                    "toolName": "echo_readonly",
                    "arguments": {"text": "merhaba"},
                },
            },
        }
    )
    denied = runtime.handle(
        {
            "id": "req_skill_mcp_denied",
            "taskId": "task_skill_mcp_denied",
            "capability": "skill.run",
            "payload": {
                "skillId": "mcp.readonly_tool_proxy",
                "payload": {
                    "serverId": "mcp_fixture",
                    "toolName": "write_note",
                    "arguments": {"path": str(tmp_path / "note.txt"), "text": "elyan"},
                },
            },
        }
    )

    assert allowed["ok"] is True
    assert "merhaba" in allowed["result"]["result"]["output"]
    assert denied["ok"] is False
    assert denied["error"]["code"] == "PERMISSION_REQUIRED"


def test_runtime_status_exposes_skill_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    skill_runtime.refresh_skill_runtime()
    runtime = bridge.RuntimeBridge()

    status = runtime.status()

    assert "skillStatus" in status
    assert status["skillStatus"]["manifestCount"] >= 7
    assert "readySkillCount" in status["skillStatus"]
    assert "blockedSkillCount" in status["skillStatus"]
