from __future__ import annotations

import json
from types import SimpleNamespace

from cli.commands import schedule


def test_schedule_falls_back_to_local_routine_engine(monkeypatch, capsys):
    monkeypatch.setattr(
        schedule.routines,
        "_api_request",
        lambda method, path, payload=None, port=18789: {"ok": False, "status": 0, "data": {"error": "connection refused"}},
    )

    captured = {}

    def _fake_create_from_text(**kwargs):
        captured.update(kwargs)
        return {"id": "rt_local_1", "name": "Sabah özeti"}

    monkeypatch.setattr(schedule.routine_engine, "create_from_text", _fake_create_from_text)

    args = SimpleNamespace(
        text=["Her", "gün", "saat", "09:00", "günlük", "özet", "gönder"],
        json=False,
        name="",
        expression="",
        panels="",
        report_channel="telegram",
        report_chat_id="",
        disabled=False,
        port=18789,
    )
    schedule.run(args)
    out = capsys.readouterr().out

    assert "Yerel zamanlandı" in out
    assert captured["text"] == "Her gün saat 09:00 günlük özet gönder"
    assert captured["report_channel"] == "telegram"


def test_schedule_prefers_gateway_when_available(monkeypatch, capsys):
    monkeypatch.setattr(
        schedule.routines,
        "_api_request",
        lambda method, path, payload=None, port=18789: {
            "ok": True,
            "status": 200,
            "data": {"routine": {"id": "rt_gateway_1", "name": "Gateway rutin"}},
        },
    )

    args = SimpleNamespace(
        text=["Hafta", "içi", "saat", "18:30", "rapor", "gönder"],
        json=True,
        name="",
        expression="",
        panels="",
        report_channel="telegram",
        report_chat_id="",
        disabled=False,
        port=18789,
    )
    schedule.run(args)
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["mode"] == "gateway"
    assert payload["routine"]["id"] == "rt_gateway_1"
