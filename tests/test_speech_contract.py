from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from runtime import state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def _reset_speech_state(speech_module: object) -> None:
    setattr(speech_module, "_ACTIVE_CAPTURE", None)
    getattr(speech_module, "_CAPTURE_HISTORY").clear()
    setattr(speech_module, "_LAST_ERROR_CODE", "")
    whisper_model = getattr(speech_module, "_whisper_model", None)
    if whisper_model is not None and hasattr(whisper_model, "cache_clear"):
        whisper_model.cache_clear()


class _FakeSoundFileWriter:
    def __init__(
        self,
        path: str,
        *,
        mode: str,
        samplerate: int,
        channels: int,
        subtype: str,
    ) -> None:
        del mode, samplerate, channels, subtype
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"RIFF")

    def write(self, _payload: object) -> None:
        if not self.path.exists():
            self.path.write_bytes(b"RIFF")

    def close(self) -> None:
        return


class _FakeSoundFileModule:
    SoundFile = _FakeSoundFileWriter


class _FakeInputStream:
    def __init__(self, *, samplerate: int, channels: int, dtype: str, callback: object) -> None:
        del samplerate, channels, dtype
        self.callback = callback

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def close(self) -> None:
        return


class _FakeSoundDeviceModule:
    CallbackStop = RuntimeError
    InputStream = _FakeInputStream


def test_bridge_status_does_not_eager_load_speech_dependencies() -> None:
    for module_name in [
        "runtime.bridge",
        "actions.speech",
        "sounddevice",
        "soundfile",
        "faster_whisper",
    ]:
        sys.modules.pop(module_name, None)

    bridge = importlib.import_module("runtime.bridge")
    runtime = bridge.RuntimeBridge()
    status = runtime.status()

    assert status["ok"] is True
    assert "actions.speech" in sys.modules
    assert "sounddevice" not in sys.modules
    assert "soundfile" not in sys.modules
    assert "faster_whisper" not in sys.modules


def test_speech_capture_requires_ui_gesture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import runtime.capability_registry as registry

    result = registry.run_capability(
        "speech_capture",
        {"action": "start", "_uiGesture": False},
        state_store.snapshot(),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "PERMISSION_REQUIRED"


def test_speech_capture_start_stop_and_status_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import actions.speech as speech
    import runtime.capability_registry as registry

    _reset_speech_state(speech)
    monkeypatch.setattr(speech, "_sounddevice_module", lambda: _FakeSoundDeviceModule)
    monkeypatch.setattr(speech, "_soundfile_module", lambda: _FakeSoundFileModule)

    start = registry.run_capability(
        "speech_capture",
        {"action": "start", "_uiGesture": True},
        state_store.snapshot(),
    )
    status = registry.run_capability(
        "speech_capture",
        {"action": "status", "_uiGesture": True},
        state_store.snapshot(),
    )
    stop = registry.run_capability(
        "speech_capture",
        {"action": "stop", "_uiGesture": True},
        state_store.snapshot(),
    )

    assert start["ok"] is True
    assert start["result"]["status"] == "recording"
    assert status["ok"] is True
    assert status["result"]["status"] == "recording"
    assert stop["ok"] is True
    assert stop["result"]["status"] == "completed"
    assert stop["result"]["audioPath"].endswith(".wav")


def test_speech_to_text_missing_dependency_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import actions.speech as speech
    import runtime.capability_registry as registry

    _reset_speech_state(speech)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(
        speech,
        "_whisper_model",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("faster_whisper")),
    )

    result = registry.run_capability(
        "speech_to_text",
        {"audioPath": str(audio_path), "languageHint": "tr"},
        state_store.snapshot(),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_speech_to_text_reads_sample_audio_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import actions.speech as speech
    import runtime.capability_registry as registry

    _reset_speech_state(speech)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(
        speech,
        "_transcribe_audio",
        lambda _path, _language: (
            "Merhaba Elyan",
            "tr",
            1200,
            [{"start": 0.0, "end": 1.2, "text": "Merhaba Elyan"}],
        ),
    )

    result = registry.run_capability(
        "speech_to_text",
        {"audioPath": str(audio_path), "languageHint": "tr"},
        state_store.snapshot(),
    )

    assert result["ok"] is True
    assert result["result"]["kind"] == "speech_to_text"
    assert result["result"]["text"] == "Merhaba Elyan"
    assert result["result"]["segments"][0]["text"] == "Merhaba Elyan"


def test_text_to_speech_uses_safe_fallback_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    import actions.tts as tts
    import runtime.capability_registry as registry

    monkeypatch.setattr(tts, "_preferred_provider", lambda _voice="": "say")
    monkeypatch.setattr(tts, "_run_say", lambda _text, _language, _voice: "say")

    result = registry.run_capability(
        "text_to_speech",
        {"text": "Merhaba Elyan", "languageHint": "tr", "interrupt": True},
        state_store.snapshot(),
    )

    assert result["ok"] is True
    assert result["result"]["kind"] == "text_to_speech"
    assert result["result"]["provider"] == "say"
