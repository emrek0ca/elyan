from __future__ import annotations

from pathlib import Path

import pytest

from runtime import bridge, state_store
from runtime import mcp_runtime
import runtime.capability_registry as registry


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


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


def _configured_state(tmp_path: Path, server_path: Path) -> dict[str, object]:
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


def test_mcp_refresh_lists_stdio_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)

    status = mcp_runtime.refresh_mcp_runtime(saved)

    assert status["sdkAvailable"] is True
    assert status["toolCount"] == 2
    assert any(tool["name"] == "echo_readonly" for tool in status["tools"])
    assert any(tool["name"] == "write_note" for tool in status["tools"])
    assert status["servers"][0]["connected"] is True
    assert status["serverCount"] == 1
    assert status["tools"][0]["available"] is True
    assert "serverName" in status["tools"][0]


def test_mcp_refresh_keeps_invalid_server_truth_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_invalid",
            "name": "broken",
            "transport": "stdio",
            "command": "",
            "args": [],
            "cwd": str(tmp_path),
            "enabled": True,
        }
    ]
    saved = state_store.save_state(state)

    status = mcp_runtime.refresh_mcp_runtime(saved)

    assert status["serverCount"] == 1
    assert status["toolCount"] == 0
    assert status["lastErrorCode"] == "MCP_SERVER_INVALID"
    assert status["servers"][0]["lastErrorCode"] == "MCP_SERVER_INVALID"
    assert status["servers"][0]["sdkAvailable"] in {True, False}


def test_mcp_read_only_tool_executes_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)

    status = mcp_runtime.refresh_mcp_runtime(saved)
    metadata = next(tool for tool in status["tools"] if tool["name"] == "echo_readonly")

    result = registry.run_capability(
        "mcp_call_tool",
        {
            "serverId": "mcp_fixture",
            "toolName": "echo_readonly",
            "arguments": {"text": "merhaba"},
            "_readOnlyHint": metadata["readOnly"],
        },
        state_store.snapshot(),
    )

    assert result["ok"] is True
    assert result["result"]["kind"] == "mcp_call_tool"
    assert result["result"]["toolName"] == "echo_readonly"
    assert "merhaba" in result["output"]


def test_mcp_side_effect_tool_requires_confirmation_then_runs_in_confirmed_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)
    mcp_runtime.refresh_mcp_runtime(saved)

    denied = registry.run_capability(
        "mcp_call_tool",
        {
            "serverId": "mcp_fixture",
            "toolName": "write_note",
            "arguments": {"path": str(tmp_path / "note.txt"), "text": "elyan"},
            "_readOnlyHint": False,
        },
        state_store.snapshot(),
    )

    assert denied["ok"] is False
    assert denied["error"]["code"] == "PERMISSION_REQUIRED"

    runtime = bridge.RuntimeBridge()
    conversation = state_store.create_conversation("MCP")
    plan = state_store.save_pending_plan(
        {
            "id": "plan_mcp_write",
            "conversationId": conversation["id"],
            "query": "mcp ile not yaz",
            "intent": "mcp_call_tool",
            "capability": "mcp_call_tool",
            "confidence": 0.88,
            "privacyClass": "local_private",
            "steps": [
                {
                    "capability": "mcp_call_tool",
                    "args": {
                        "serverId": "mcp_fixture",
                        "toolName": "write_note",
                        "arguments": {"path": str(tmp_path / "note.txt"), "text": "elyan"},
                        "_readOnlyHint": False,
                    },
                    "description": "MCP ile not yaz",
                }
            ],
            "planPreview": {
                "summary": "MCP aracı write_note çalıştırılacak.",
                "steps": [{"capability": "mcp_call_tool"}],
            },
        }
    )

    result = runtime.confirm_conversation_plan(str(conversation["id"]), str(plan["id"]), True)

    assert result["chatOk"] is True
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "elyan"
    assert result["structuredResult"]["toolName"] == "write_note"


def test_runtime_status_exposes_mcp_truth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)
    mcp_runtime.refresh_mcp_runtime(saved)

    runtime = bridge.RuntimeBridge()
    status = runtime.status()

    assert "mcpStatus" in status
    assert status["dependencyStatus"]["mcp"]["label"] == "MCP Python SDK"
    assert status["mcpStatus"]["toolCount"] == 2
    assert status["mcpStatus"]["serverCount"] == 1
