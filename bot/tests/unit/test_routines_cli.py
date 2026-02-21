"""Unit tests for routines CLI output and JSON mode."""

import json
from types import SimpleNamespace

from cli.commands import routines


def test_routines_list_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        routines,
        "_api_request",
        lambda method, path, payload=None, port=18789: {
            "ok": True,
            "status": 200,
            "data": {
                "summary": {"total": 1, "enabled": 1},
                "routines": [
                    {
                        "id": "abc123",
                        "name": "Sabah",
                        "expression": "0 9 * * *",
                        "enabled": True,
                        "report_channel": "telegram",
                    }
                ],
            },
        },
    )
    args = SimpleNamespace(action="list", json=True, port=18789)
    routines.run(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 1
    assert payload["routines"][0]["id"] == "abc123"


def test_routines_run_json_output(monkeypatch, capsys):
    monkeypatch.setattr(routines, "_resolve_routine_id", lambda port, raw_id: ("abc123", None))
    monkeypatch.setattr(
        routines,
        "_api_request",
        lambda method, path, payload=None, port=18789: {
            "ok": True,
            "status": 200,
            "data": {"result": {"success": True, "duration_s": 1.2, "summary": "ok"}},
        },
    )
    args = SimpleNamespace(action="run", id="abc", json=True, port=18789)
    routines.run(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["id"] == "abc123"
    assert payload["result"]["success"] is True


def test_routines_suggest_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        routines,
        "_api_request",
        lambda method, path, payload=None, port=18789: {
            "ok": True,
            "status": 200,
            "data": {
                "suggestion": {
                    "name": "Akıllı Rutin",
                    "expression": "0 9 * * *",
                    "template_id": "ecommerce-daily",
                    "confidence": 0.9,
                }
            },
        },
    )
    args = SimpleNamespace(action="suggest", text="her gün saat 9 e-ticaret kontrol", json=True, port=18789)
    routines.run(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["suggestion"]["template_id"] == "ecommerce-daily"


def test_routines_add_with_text_uses_from_text_endpoint(monkeypatch, capsys):
    captured = {}

    def _fake_request(method, path, payload=None, port=18789):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload or {}
        return {
            "ok": True,
            "status": 200,
            "data": {"routine": {"id": "nl123", "name": "NL Rutin"}},
        }

    monkeypatch.setattr(routines, "_api_request", _fake_request)
    args = SimpleNamespace(
        action="add",
        text="Her gün saat 09:00 panel kontrol et rapor gönder",
        name="",
        expression="",
        steps="",
        template_id="",
        panels="",
        report_channel="telegram",
        report_chat_id="",
        disabled=False,
        json=True,
        port=18789,
    )
    routines.run(args)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert captured["path"] == "/api/routines/from-text"
