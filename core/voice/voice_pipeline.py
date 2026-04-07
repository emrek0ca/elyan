"""
core/voice/voice_pipeline.py
───────────────────────────────────────────────────────────────────────────────
VoicePipeline — full voice loop for Jarvis

Flow:
  [Wake Word] → [Record Audio] → [STT] → [JarvisCore] → [TTS] → [Speak]

State machine:
  IDLE → LISTENING (on wake) → PROCESSING (STT done) → SPEAKING → IDLE
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from enum import Enum
from utils.logger import get_logger

logger = get_logger("voice_pipeline")

_RECORD_SECONDS = 7      # max listen duration after wake
_SILENCE_TIMEOUT = 2.5   # stop recording after N seconds of silence


class PipelineState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


class VoicePipeline:
    """
    Orchestrates the full voice interaction cycle.

    Example:
        pipeline = get_voice_pipeline(agent)
        await pipeline.start()   # begins background wake-word loop
        await pipeline.stop()
    """

    def __init__(self, agent=None) -> None:
        self._agent = agent
        self._state = PipelineState.IDLE
        self._running = False
        self._main_task: asyncio.Task | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def state(self) -> PipelineState:
        return self._state

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Wire wake word callback
        from core.voice.wake_word import get_wake_word_detector
        detector = get_wake_word_detector()
        detector.set_callback(self._on_wake)
        await detector.start()

        logger.info("VoicePipeline started")

    async def stop(self) -> None:
        self._running = False
        from core.voice.wake_word import get_wake_word_detector
        await get_wake_word_detector().stop()
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
        logger.info("VoicePipeline stopped")

    async def trigger(self) -> None:
        """Manually trigger a voice interaction (from UI button)."""
        await self._on_wake()

    # ── Pipeline Stages ──────────────────────────────────────────────────────

    async def _on_wake(self) -> None:
        """Called when wake word is detected."""
        if self._state != PipelineState.IDLE:
            return  # ignore if already processing

        logger.info("Wake detected — starting voice capture")
        self._main_task = asyncio.create_task(self._run_cycle())

    async def _run_cycle(self) -> None:
        """Single wake → listen → process → speak cycle."""
        try:
            # Acknowledge wake
            from core.voice.jarvis_tts import get_jarvis_tts
            tts = get_jarvis_tts()
            await tts.speak("Dinliyorum.", interrupt=True)

            # Record
            self._state = PipelineState.LISTENING
            audio_path = await self._record_audio()
            if not audio_path:
                self._state = PipelineState.IDLE
                return

            # Transcribe
            self._state = PipelineState.PROCESSING
            text = await self._transcribe(audio_path)
            if not text.strip():
                await tts.speak("Anlayamadım, tekrar söyler misin?")
                self._state = PipelineState.IDLE
                return

            logger.info(f"Voice input: '{text}'")

            # Process with JarvisCore
            response_text = await self._process(text)

            # Speak response
            self._state = PipelineState.SPEAKING
            await tts.speak(response_text)

        except Exception as exc:
            logger.warning(f"Voice cycle error: {exc}")
        finally:
            self._state = PipelineState.IDLE

    async def _record_audio(self) -> str | None:
        """Record microphone input, return temp wav path or None."""
        try:
            import pyaudio
            import wave

            RATE = 16000
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            CHANNELS = 1

            pa = pyaudio.PyAudio()
            stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

            frames = []
            silent_chunks = 0
            silence_threshold = 300  # amplitude threshold
            max_chunks = int(RATE / CHUNK * _RECORD_SECONDS)
            silence_max = int(RATE / CHUNK * _SILENCE_TIMEOUT)

            for _ in range(max_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)

                # Simple silence detection via amplitude
                amplitude = max(abs(int.from_bytes(data[i:i+2], "little", signed=True))
                               for i in range(0, min(len(data), 200), 2))
                if amplitude < silence_threshold:
                    silent_chunks += 1
                    if silent_chunks > silence_max:
                        break
                else:
                    silent_chunks = 0

            stream.stop_stream()
            stream.close()
            pa.terminate()

            if not frames:
                return None

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(pa.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join(frames))
            return tmp_path

        except ImportError:
            logger.debug("pyaudio not available — skipping audio capture")
            return None
        except Exception as exc:
            logger.warning(f"Record error: {exc}")
            return None

    async def _transcribe(self, wav_path: str) -> str:
        """Transcribe wav file using existing STT engine."""
        try:
            from tools.voice.local_stt import stt_engine
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, stt_engine.transcribe, wav_path)
            return str(result or "").strip()
        except Exception as exc:
            logger.warning(f"STT error: {exc}")
            return ""
        finally:
            import os
            try:
                os.unlink(wav_path)
            except Exception:
                pass

    async def _process(self, text: str) -> str:
        """Pass text through JarvisCore and return response string."""
        try:
            from core.jarvis.jarvis_core import get_jarvis_core
            response = await get_jarvis_core().handle(text, "voice")
            # Strip markdown for speech
            return response.text[:400]
        except Exception as exc:
            logger.warning(f"JarvisCore error: {exc}")
            return "Bir hata oluştu, lütfen tekrar dene."


_instance: VoicePipeline | None = None


def get_voice_pipeline(agent=None) -> VoicePipeline:
    global _instance
    if _instance is None:
        _instance = VoicePipeline(agent)
    return _instance


__all__ = ["PipelineState", "VoicePipeline", "get_voice_pipeline"]
