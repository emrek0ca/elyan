from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.voice import voice_manager


@pytest.mark.asyncio
async def test_voice_manager_start_stop_and_status(monkeypatch):
    import asyncio

    class _FakeSTT:
        pass

    class _FakeTTS:
        async def synthesize(self, text, output_file=None):
            _ = (text, output_file)
            return True

    class _FakeWakeDetector:
        def __init__(self, callback=None):
            self.callback = callback
            self.started = False
            self.stopped = False
            self._stop = asyncio.Event()

        async def start(self):
            self.started = True
            await self._stop.wait()

        async def stop(self):
            self.stopped = True
            self._stop.set()

    monkeypatch.setattr(voice_manager, "get_stt_service", lambda: _FakeSTT())
    monkeypatch.setattr(voice_manager, "get_tts_service", lambda: _FakeTTS())
    monkeypatch.setattr(voice_manager, "WakeWordDetector", _FakeWakeDetector)
    monkeypatch.setattr(
        voice_manager,
        "detect_runtime_profile",
        lambda: type(
            "_Profile",
            (),
            {
                "to_dict": lambda self: {
                    "recommended_provider": "ollama",
                    "tts_backend": "macos_say",
                    "stt_backend": "whisper",
                }
            },
        )(),
    )
    monkeypatch.setattr(voice_manager.elyan_config, "get", lambda key, default=None: "elyan" if key == "voice.wake_word" else default)

    vm = voice_manager.VoiceManager()
    started = await vm.start()
    assert started["running"] is True
    assert started["stt_provider"] == "whisper"
    assert started["tts_provider"] == "macos_say"
    assert started["wake_word"] == "elyan"
    assert started["wake_word_listener"] is True
    assert started["runtime_profile"]["recommended_provider"] == "ollama"

    stopped = await vm.stop()
    assert stopped["running"] is False
    assert stopped["wake_word_listener"] is False
