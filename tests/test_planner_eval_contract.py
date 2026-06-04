from __future__ import annotations

from pathlib import Path

import pytest

from runtime import bridge, state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_path = tmp_path / "elyan_state.json"
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", state_path)
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def test_eval_missing_document_target_clarifies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_eval_missing_doc",
            "taskId": "task_eval_missing_doc",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "bu belgeyi özetle"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["clarificationNeeded"] is True
    assert "belge" in response["result"]["clarificationQuestion"].lower()


def test_eval_missing_data_target_clarifies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_eval_missing_data",
            "taskId": "task_eval_missing_data",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "bu tabloyu analiz et"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["clarificationNeeded"] is True
    assert "csv/json" in response["result"]["clarificationQuestion"].lower()


def test_eval_complex_document_request_prefers_plan_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()

    response = runtime.handle(
        {
            "id": "req_eval_docx_plan",
            "taskId": "task_eval_docx_plan",
            "capability": "conversation.send",
            "payload": {
                "conversationId": "",
                "text": "ürün özetini notes.docx olarak hazırla",
            },
        }
    )

    assert response["ok"] is True
    assert response["result"]["needsConfirmation"] is True
    assert response["result"]["planPreview"] is not None


def test_eval_response_message_stays_short_for_simple_math(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    monkeypatch.setattr(
        bridge,
        "route_text_to_tool",
        lambda _text, **_kwargs: bridge.RoutedTask(
            "math_solve",
            {"expression": "2 + 2", "mode": "evaluate"},
            "math_solve",
            intent="math_solve",
            confidence=0.98,
        ),
    )
    monkeypatch.setattr(
        bridge,
        "run_capability",
        lambda _capability, _args, _state: {
            "ok": True,
            "tool": "math_solve",
            "output": "4",
            "result": {"kind": "math_solve", "result": "4"},
            "artifacts": [],
            "error": None,
        },
    )

    response = runtime.handle(
        {
            "id": "req_eval_short_math",
            "taskId": "task_eval_short_math",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "2+2 kaç?"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["assistantMessage"] == "4"


def test_eval_mcp_readonly_plan_keeps_confirmation_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    monkeypatch.setattr(bridge, "route_text_to_tool", lambda _text, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_semantic_route",
        lambda _state, _conversation, _text, **_kwargs: {
            "intent": "mcp_call_tool",
            "capability": "mcp_call_tool",
            "args": {
                "serverId": "mcp_fs",
                "toolName": "echo_readonly",
                "arguments": {"text": "elyan"},
                "_readOnlyHint": True,
            },
            "confidence": 0.94,
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": "local_private",
            "planPreview": None,
            "provider": "ollama",
        },
    )
    monkeypatch.setattr(
        bridge,
        "_execute_capability_with_preprocessing",
        lambda _capability, _args, _state, source: (
            {
                "ok": True,
                "tool": "mcp_call_tool",
                "output": "elyan",
                "result": {"kind": "mcp_call_tool"},
                "artifacts": [],
                "error": None,
            },
            [{"tool": "mcp_call_tool", "source": source}],
        ),
    )

    response = runtime.handle(
        {
            "id": "req_eval_mcp_readonly",
            "taskId": "task_eval_mcp_readonly",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "readonly mcp aracını çalıştır"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["needsConfirmation"] is False
    assert response["result"]["assistantMessage"] == "elyan"


def test_eval_mcp_side_effect_plan_forces_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    monkeypatch.setattr(bridge, "route_text_to_tool", lambda _text, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_semantic_route",
        lambda _state, _conversation, _text, **_kwargs: {
            "intent": "mcp_call_tool",
            "capability": "mcp_call_tool",
            "args": {
                "serverId": "mcp_fs",
                "toolName": "write_note",
                "arguments": {"path": "/tmp/note.txt"},
                "_readOnlyHint": False,
            },
            "confidence": 0.95,
            "requiresConfirmation": True,
            "isMultiStep": False,
            "privacyClass": "local_private",
            "planPreview": None,
            "provider": "ollama",
        },
    )

    response = runtime.handle(
        {
            "id": "req_eval_mcp_write",
            "taskId": "task_eval_mcp_write",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "mcp ile not yaz"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["needsConfirmation"] is True
    assert response["result"]["planPreview"] is not None


def test_eval_skill_route_uses_plan_for_write_skill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    monkeypatch.setattr(bridge, "route_text_to_tool", lambda _text, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_semantic_route",
        lambda _state, _conversation, _text, **_kwargs: {
            "intent": "run_skill",
            "capability": "run_skill",
            "args": {
                "skillId": "document.docx_from_context",
                "payload": {"prompt": "özet", "outputPath": "notes.docx"},
            },
            "confidence": 0.96,
            "requiresConfirmation": True,
            "isMultiStep": False,
            "privacyClass": "local_private",
            "planPreview": {
                "summary": "notes.docx üretilecek.",
                "steps": [{"capability": "run_skill", "description": "skill çalıştır"}],
            },
            "provider": "ollama",
        },
    )

    response = runtime.handle(
        {
            "id": "req_eval_skill_write",
            "taskId": "task_eval_skill_write",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "skill ile docx hazırla"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["needsConfirmation"] is True
    assert response["result"]["planPreview"] is not None


def test_eval_retrieval_clarification_keeps_retrieval_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    monkeypatch.setattr(bridge, "route_text_to_tool", lambda _text, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_semantic_route",
        lambda _state, _conversation, _text, **_kwargs: {
            "intent": "document_read",
            "capability": "document_read",
            "args": {"mode": "summary"},
            "confidence": 0.91,
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": "local_private",
            "planPreview": None,
            "provider": "ollama",
            "retrieval": {
                "strategy": "embedding",
                "matches": [
                    {"source": "workspace", "path": "/tmp/notes.md"},
                    {"source": "conversations", "id": "conv_1"},
                ],
            },
        },
    )

    response = runtime.handle(
        {
            "id": "req_eval_retrieval_clarify",
            "taskId": "task_eval_retrieval_clarify",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "önceki notu özetle"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["clarificationNeeded"] is True
    assert response["result"]["retrievalUsed"] is True
    assert response["result"]["retrievalSources"] == ["conversations", "workspace"]


def test_eval_repeated_misroute_history_forces_clarification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()
    state_store.record_route_outcome(
        outcome="misrouted",
        query="finder aç",
        intent="open_app",
        capability="open_app",
    )
    state_store.record_route_outcome(
        outcome="misrouted",
        query="finder aç",
        intent="open_app",
        capability="open_app",
    )
    monkeypatch.setattr(bridge, "route_text_to_tool", lambda _text, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_semantic_route",
        lambda _state, _conversation, _text, **_kwargs: {
            "intent": "open_app",
            "capability": "open_app",
            "args": {"app_name": "Finder"},
            "confidence": 0.98,
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": "local_private",
            "planPreview": None,
            "provider": "ollama",
        },
    )

    response = runtime.handle(
        {
            "id": "req_eval_misroute_history",
            "taskId": "task_eval_misroute_history",
            "capability": "conversation.send",
            "payload": {"conversationId": "", "text": "finder aç"},
        }
    )

    assert response["ok"] is True
    assert response["result"]["clarificationNeeded"] is True
    assert "netleştir" in response["result"]["clarificationQuestion"].lower()
