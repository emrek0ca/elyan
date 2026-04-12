from types import SimpleNamespace

import pytest

from cli.commands import message as message_cmd


@pytest.mark.asyncio
async def test_show_status_uses_system_overview(monkeypatch, capsys):
    async def fake_fetch(path: str, *, timeout: float = 10.0):
        assert path == "/api/v1/system/overview"
        return True, {
            "readiness": {
                "elyan_ready": True,
                "connected_provider": "ollama",
                "connected_model": "llama3.2",
            },
            "platforms": {"summary": {"connected_channels": 2, "configured_channels": 3}},
            "skills": {"enabled": 4, "issues": 1},
            "providers": {"summary": {"available": 2, "auth_required": 1}},
        }, ""

    monkeypatch.setattr(message_cmd, "_fetch_json", fake_fetch)

    code = await message_cmd.show_status(as_json=False)
    out = capsys.readouterr().out

    assert code == 0
    assert "Operator message status" in out
    assert "ollama / llama3.2" in out
    assert "2 live / 3 configured" in out


@pytest.mark.asyncio
async def test_show_stack_summarizes_gateway_payloads(monkeypatch, capsys):
    async def fake_fetch(path: str, *, timeout: float = 10.0):
        mapping = {
            "/api/skills": (True, {"summary": {"installed": 5, "enabled": 3}}, ""),
            "/api/skills/workflows": (True, {"summary": {"total": 4, "enabled": 2}}, ""),
            "/api/routines": (True, {"summary": {"total": 6, "enabled": 4}}, ""),
        }
        return mapping[path]

    monkeypatch.setattr(message_cmd, "_fetch_json", fake_fetch)

    code = await message_cmd.show_stack(as_json=False)
    out = capsys.readouterr().out

    assert code == 0
    assert "Operator stack" in out
    assert "3/5 enabled" in out
    assert "2/4 enabled" in out
    assert "4/6 active" in out


def test_handle_message_defaults_to_status(monkeypatch):
    captured = {}

    async def fake_show_status(*, as_json: bool = False):
        captured["json"] = as_json
        return 0

    monkeypatch.setattr(message_cmd, "show_status", fake_show_status)

    code = message_cmd.handle_message(SimpleNamespace(action=None, json=True))

    assert code == 0
    assert captured["json"] is True
