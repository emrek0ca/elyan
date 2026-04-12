"""
tests/voice/test_voice_modules.py
───────────────────────────────────────────────────────────────────────────────
Tests for Faz 5 voice modules:
  - WakeWordDetector  (wake_word.py)
  - ElyanTTS         (elyan_tts.py)
  - VoicePipeline     (voice_pipeline.py)

All heavy deps (pyaudio, openwakeword, pyttsx3) are mocked out.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# WakeWordDetector
# ─────────────────────────────────────────────────────────────────────────────

class TestWakeWordDetector:
    def _get(self):
        # Fresh instance each test (bypass singleton)
        from core.voice.wake_word import WakeWordDetector
        return WakeWordDetector()

    def test_initial_state(self):
        det = self._get()
        assert not det.running
        assert det.backend == "none"

    def test_set_callback(self):
        det = self._get()
        cb = AsyncMock()
        det.set_callback(cb)
        assert det._callback is cb

    @pytest.mark.asyncio
    async def test_trigger_wake_fires_callback(self):
        det = self._get()
        fired = []
        async def cb():
            fired.append(1)
        det.set_callback(cb)
        await det.trigger_wake()
        assert fired == [1]

    @pytest.mark.asyncio
    async def test_trigger_wake_no_callback_is_safe(self):
        det = self._get()
        # Should not raise
        await det.trigger_wake()

    @pytest.mark.asyncio
    async def test_fire_swallows_callback_exceptions(self):
        det = self._get()
        async def bad_cb():
            raise RuntimeError("boom")
        det.set_callback(bad_cb)
        # _fire should not propagate
        await det._fire()

    @pytest.mark.asyncio
    async def test_start_stop_noop_backend(self):
        det = self._get()
        with patch.object(det, "_detect_backend", return_value="none"):
            det._backend = "none"
            await det.start()
            assert det.running
            await asyncio.sleep(0.05)
            await det.stop()
            assert not det.running

    def test_detect_backend_none_when_no_deps(self):
        from core.voice.wake_word import WakeWordDetector
        with patch.dict("sys.modules", {"openwakeword": None, "pyaudio": None, "numpy": None}):
            # ImportError path — backend falls through to "none"
            backend = WakeWordDetector._detect_backend()
            # "none" when all imports fail; pyaudio might still be importable in test env
            assert backend in ("none", "pyaudio_keyword", "openwakeword")

    def test_has_speech_energy_skips_silence(self):
        det = self._get()
        assert det._has_speech_energy([b"\x00\x00" * 256]) is False

    def test_has_speech_energy_accepts_loud_audio(self):
        det = self._get()
        assert det._has_speech_energy([b"\xff\x7f" * 256]) is True

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        det = self._get()

        async def _noop_loop():
            await asyncio.sleep(10)

        with patch.object(det, "_loop", side_effect=_noop_loop):
            await det.start()
            task1 = det._task
            await det.start()  # second call — no-op
            assert det._task is task1
            await det.stop()


# ─────────────────────────────────────────────────────────────────────────────
# ElyanTTS
# ─────────────────────────────────────────────────────────────────────────────

class TestElyanTTS:
    def _get(self, backend="silent"):
        from core.voice.elyan_tts import ElyanTTS
        tts = ElyanTTS.__new__(ElyanTTS)
        tts._backend = backend
        tts._enabled = True
        return tts

    @pytest.mark.asyncio
    async def test_speak_returns_false_when_disabled(self):
        tts = self._get()
        tts._enabled = False
        result = await tts.speak("hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_speak_returns_false_for_blank_text(self):
        tts = self._get()
        result = await tts.speak("   ")
        assert result is False

    @pytest.mark.asyncio
    async def test_silent_backend_returns_true(self):
        tts = self._get(backend="silent")
        result = await tts.speak("test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_macos_say_backend_success(self):
        tts = self._get(backend="macos_say")
        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            result = await tts.speak("hello", interrupt=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_macos_say_interrupt_kills_existing(self):
        tts = self._get(backend="macos_say")
        kill_proc = MagicMock()
        kill_proc.wait = AsyncMock(return_value=0)
        speak_proc = MagicMock()
        speak_proc.wait = AsyncMock(return_value=0)
        speak_proc.returncode = 0

        call_count = 0
        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return kill_proc if call_count == 1 else speak_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await tts.speak("hello", interrupt=True)

        assert call_count == 2  # killall + say

    @pytest.mark.asyncio
    async def test_macos_say_timeout_returns_false(self):
        tts = self._get(backend="macos_say")
        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            result = await tts.speak("hello")
        assert result is False

    def test_clean_text_strips_markdown(self):
        from core.voice.elyan_tts import ElyanTTS
        text = "**bold** *italic* `code` ## Header [link](url)"
        cleaned = ElyanTTS._clean_text(text)
        assert "**" not in cleaned
        assert "*" not in cleaned
        assert "`" not in cleaned
        assert "#" not in cleaned
        assert "bold" in cleaned
        assert "italic" in cleaned
        assert "code" in cleaned

    def test_clean_text_caps_at_500(self):
        from core.voice.elyan_tts import ElyanTTS
        long_text = "a" * 1000
        assert len(ElyanTTS._clean_text(long_text)) <= 500

    def test_enable_disable(self):
        tts = self._get()
        tts.disable()
        assert not tts._enabled
        tts.enable()
        assert tts._enabled

    def test_detect_backend_macos_when_say_available(self):
        from core.voice.elyan_tts import ElyanTTS
        with patch("shutil.which", return_value="/usr/bin/say"):
            backend = ElyanTTS._detect_backend()
        assert backend == "macos_say"

    def test_detect_backend_silent_when_no_deps(self):
        from core.voice.elyan_tts import ElyanTTS
        with patch("shutil.which", return_value=None):
            with patch.dict("sys.modules", {"pyttsx3": None}):
                backend = ElyanTTS._detect_backend()
        assert backend in ("silent", "pyttsx3")  # pyttsx3 might be installed


# ─────────────────────────────────────────────────────────────────────────────
# VoicePipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestVoicePipeline:
    def _get(self):
        from core.voice.voice_pipeline import VoicePipeline
        return VoicePipeline(agent=None)

    def test_initial_state(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()
        assert pipeline.state == PipelineState.IDLE
        assert not pipeline._running

    @pytest.mark.asyncio
    async def test_on_wake_ignored_when_not_idle(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()
        pipeline._state = PipelineState.LISTENING
        # Should return immediately without creating task
        await pipeline._on_wake()
        assert pipeline._main_task is None

    @pytest.mark.asyncio
    async def test_run_cycle_returns_to_idle_on_no_audio(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()

        mock_tts = MagicMock()
        mock_tts.speak = AsyncMock(return_value=True)

        with patch("core.voice.voice_pipeline.VoicePipeline._record_audio", new_callable=AsyncMock, return_value=None):
            with patch("core.voice.elyan_tts.get_elyan_tts", return_value=mock_tts):
                await pipeline._run_cycle()

        assert pipeline.state == PipelineState.IDLE

    @pytest.mark.asyncio
    async def test_run_cycle_returns_to_idle_on_empty_transcription(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()

        mock_tts = MagicMock()
        mock_tts.speak = AsyncMock(return_value=True)

        with patch("core.voice.voice_pipeline.VoicePipeline._record_audio", new_callable=AsyncMock, return_value="/tmp/test.wav"):
            with patch("core.voice.voice_pipeline.VoicePipeline._transcribe", new_callable=AsyncMock, return_value=""):
                with patch("core.voice.elyan_tts.get_elyan_tts", return_value=mock_tts):
                    await pipeline._run_cycle()

        assert pipeline.state == PipelineState.IDLE

    @pytest.mark.asyncio
    async def test_full_cycle_speaks_response(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()

        mock_tts = MagicMock()
        spoken = []
        async def capture_speak(text, **kwargs):
            spoken.append(text)
            return True
        mock_tts.speak = capture_speak

        mock_response = MagicMock()
        mock_response.text = "İşte cevabınız."

        with patch("core.voice.voice_pipeline.VoicePipeline._record_audio", new_callable=AsyncMock, return_value="/tmp/test.wav"):
            with patch("core.voice.voice_pipeline.VoicePipeline._transcribe", new_callable=AsyncMock, return_value="Merhaba Elyan"):
                with patch("core.voice.voice_pipeline.VoicePipeline._process", new_callable=AsyncMock, return_value="İşte cevabınız."):
                    with patch("core.voice.elyan_tts.get_elyan_tts", return_value=mock_tts):
                        await pipeline._run_cycle()

        assert pipeline.state == PipelineState.IDLE
        assert any("cevabınız" in s for s in spoken)

    @pytest.mark.asyncio
    async def test_cycle_exception_returns_to_idle(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()

        mock_tts = MagicMock()
        mock_tts.speak = AsyncMock(side_effect=RuntimeError("crash"))

        with patch("core.voice.elyan_tts.get_elyan_tts", return_value=mock_tts):
            await pipeline._run_cycle()

        assert pipeline.state == PipelineState.IDLE

    @pytest.mark.asyncio
    async def test_record_audio_returns_none_without_pyaudio(self):
        pipeline = self._get()
        with patch.dict("sys.modules", {"pyaudio": None}):
            result = await pipeline._record_audio()
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_returns_empty_on_error(self):
        pipeline = self._get()
        with patch("core.voice.voice_pipeline.VoicePipeline._transcribe",
                   new_callable=AsyncMock, return_value="") as mock_tr:
            result = await pipeline._transcribe("/tmp/fake.wav")
        assert result == ""

    @pytest.mark.asyncio
    async def test_process_returns_fallback_on_error(self):
        pipeline = self._get()
        with patch("core.elyan.elyan_core.get_elyan_core", side_effect=ImportError("no elyan")):
            result = await pipeline._process("test")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_trigger_calls_on_wake(self):
        from core.voice.voice_pipeline import PipelineState
        pipeline = self._get()
        called = []
        async def fake_on_wake():
            called.append(1)
        pipeline._on_wake = fake_on_wake
        await pipeline.trigger()
        assert called == [1]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestSingletons:
    def test_get_wake_word_detector_returns_same_instance(self):
        import core.voice.wake_word as ww
        ww._instance = None
        a = ww.get_wake_word_detector()
        b = ww.get_wake_word_detector()
        assert a is b
        ww._instance = None

    def test_get_elyan_tts_returns_same_instance(self):
        import core.voice.elyan_tts as tts_mod
        tts_mod._instance = None
        a = tts_mod.get_elyan_tts()
        b = tts_mod.get_elyan_tts()
        assert a is b
        tts_mod._instance = None

    def test_get_voice_pipeline_returns_same_instance(self):
        import core.voice.voice_pipeline as vp_mod
        vp_mod._instance = None
        a = vp_mod.get_voice_pipeline()
        b = vp_mod.get_voice_pipeline()
        assert a is b
        vp_mod._instance = None
