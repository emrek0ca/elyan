import asyncio
from types import SimpleNamespace

import pytest

from core.voice.stt_engine import _OpenAIWhisperSTT
from tools.voice.local_stt import LocalSTT


def test_local_stt_transcribe_sync_returns_text(monkeypatch, tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"wav")

    stt = LocalSTT(model_size="base")
    stt.model = SimpleNamespace(transcribe=lambda path, fp16=False: {"text": "  merhaba dunya  "})
    stt._load_model = lambda: None

    assert stt.transcribe_sync(str(audio_path)) == "merhaba dunya"


@pytest.mark.asyncio
async def test_local_stt_transcribe_async_uses_sync_path(monkeypatch, tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"wav")

    stt = LocalSTT(model_size="base")
    calls = []

    def fake_sync(path: str) -> str:
        calls.append(path)
        return "hazir"

    monkeypatch.setattr(stt, "transcribe_sync", fake_sync)

    assert await stt.transcribe(str(audio_path)) == "hazir"
    assert calls == [str(audio_path)]


def test_openai_whisper_fallback_uses_legacy_sync_transcribe(monkeypatch):
    fake_legacy = SimpleNamespace(
        transcribe_sync=lambda wav_path: f"legacy:{wav_path}",
        transcribe=lambda wav_path: asyncio.sleep(0, result="unexpected"),
    )
    monkeypatch.setattr("tools.voice.local_stt.stt_engine", fake_legacy)

    fallback = _OpenAIWhisperSTT()

    assert fallback.transcribe("/tmp/voice.wav") == "legacy:/tmp/voice.wav"
