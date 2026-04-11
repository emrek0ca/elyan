from types import SimpleNamespace

from cli.commands import digest


class _FakeDigestManager:
    async def get_proactive_briefing(self, **kwargs):
        _ = kwargs
        return {
            "success": True,
            "briefing": "Günün özeti hazır.",
            "digest": {
                "summary": "Günün özeti hazır.",
                "speech_script": "Günaydın. Takviminde iki toplantı var.",
                "calendar_items": [{"title": "Standup"}],
                "email_items": [],
                "news_items": [],
                "system_notes": [],
                "proactive_actions": [],
                "source_trace": {},
            },
            "renders": {
                "terminal": "Günün özeti hazır.",
                "mobile": "Günün özeti hazır.",
                "speech": "Günaydın. Takviminde iki toplantı var.",
            },
        }


def test_digest_run_show_prints_terminal_render(monkeypatch, capsys):
    monkeypatch.setattr("cli.commands.digest.get_briefing_manager", lambda: _FakeDigestManager(), raising=False)

    code = digest.run(
        SimpleNamespace(
            subcommand="show",
            format="text",
            file=None,
            weather=True,
            calendar=True,
            news=True,
            email=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "Günün özeti hazır." in captured.out


def test_digest_run_speak_uses_local_tts(monkeypatch):
    spoken = {}

    class _FakeTTS:
        async def speak(self, text: str, interrupt: bool = False) -> bool:
            spoken["text"] = text
            spoken["interrupt"] = interrupt
            return True

    monkeypatch.setattr("cli.commands.digest.get_briefing_manager", lambda: _FakeDigestManager(), raising=False)
    monkeypatch.setattr("cli.commands.digest.get_elyan_tts", lambda: _FakeTTS(), raising=False)

    code = digest.run(
        SimpleNamespace(
            subcommand="speak",
            format="text",
            file=None,
            weather=True,
            calendar=True,
            news=True,
            email=True,
        )
    )

    assert code == 0
    assert spoken["text"] == "Günaydın. Takviminde iki toplantı var."
    assert spoken["interrupt"] is True
