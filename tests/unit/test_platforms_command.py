from __future__ import annotations

import json
from types import SimpleNamespace

from cli.commands import platforms as platforms_cmd


def test_platforms_json_includes_live_channel_status(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    elyan_dir = tmp_path / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)
    (elyan_dir / "elyan.json").write_text(
        json.dumps(
            {
                "channels": [
                    {"type": "telegram", "id": "telegram", "enabled": True},
                    {"type": "whatsapp", "id": "whatsapp", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    (elyan_dir / "gateway.pid").write_text(str(99999), encoding="utf-8")

    monkeypatch.setattr(platforms_cmd.os, "kill", lambda pid, sig: None)

    class FakeGateway:
        @staticmethod
        def _fetch_gateway_channels(_port: int):
            return {
                "ok": True,
                "channels": [
                    {"type": "telegram", "status": "connected", "detail": "bot online"},
                    {"type": "whatsapp", "status": "degraded", "detail": "retrying"},
                ],
            }

    monkeypatch.setattr("cli.commands.gateway", FakeGateway, raising=False)

    code = platforms_cmd.run(SimpleNamespace(json=True))

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    surfaces = {item["name"]: item for item in payload["surfaces"]}
    assert surfaces["telegram"]["status"] == "connected"
    assert surfaces["telegram"]["active"] is True
    assert surfaces["whatsapp"]["status"] == "degraded"
    assert surfaces["whatsapp"]["detail"] == "retrying"
    assert surfaces["whatsapp"]["active"] is True


def test_platforms_text_output_shows_next_actions(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    elyan_dir = tmp_path / ".elyan"
    elyan_dir.mkdir(parents=True, exist_ok=True)
    (elyan_dir / "elyan.json").write_text("{}", encoding="utf-8")

    code = platforms_cmd.run(SimpleNamespace(json=False))

    assert code == 0
    out = capsys.readouterr().out
    assert "Elyan platforms" in out
    assert "elyan desktop" in out
    assert "elyan channels add --type telegram" in out
