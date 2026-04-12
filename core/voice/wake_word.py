"""
core/voice/wake_word.py
───────────────────────────────────────────────────────────────────────────────
Wake Word Detector — "Hey Elyan"

Strategy (graceful degradation):
  1. openwakeword (pip install openwakeword) — best quality, CPU
  2. macOS SFSpeechRecognizer via subprocess / Automator — built-in
  3. Keyboard shortcut fallback (Ctrl+Space) — always available

The detector runs in a background asyncio task.
On detection it calls the registered async callback.
"""
from __future__ import annotations

import asyncio
import audioop
from typing import Callable, Awaitable
from utils.logger import get_logger

logger = get_logger("wake_word")

WakeCallback = Callable[[], Awaitable[None]]

# Keywords that trigger wake (Turkish + English variants)
_WAKE_PHRASES = {"hey elyan", "elyan", "hey elian", "elian"}
_MIN_WAKE_RMS = 250


class WakeWordDetector:
    """
    Wake word detector with two backends:
      - openwakeword  (if available)
      - keyword-in-transcript fallback via Whisper streaming
    Falls back gracefully if neither is available.
    """

    def __init__(self) -> None:
        self._callback: WakeCallback | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._backend: str = "none"

    def set_callback(self, callback: WakeCallback) -> None:
        self._callback = callback

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._backend = self._detect_backend()
        logger.info(f"Wake word detector starting (backend: {self._backend})")
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @staticmethod
    def _detect_backend() -> str:
        try:
            import openwakeword  # noqa: F401
            return "openwakeword"
        except ImportError:
            pass
        try:
            import pyaudio  # noqa: F401
            import numpy  # noqa: F401
            return "pyaudio_keyword"
        except ImportError:
            pass
        return "none"

    async def _loop(self) -> None:
        if self._backend == "openwakeword":
            await self._loop_openwakeword()
        elif self._backend == "pyaudio_keyword":
            await self._loop_pyaudio_keyword()
        else:
            await self._loop_noop()

    async def _loop_openwakeword(self) -> None:
        """openwakeword-based detection (best quality)."""
        try:
            import pyaudio
            import numpy as np
            from openwakeword.model import Model

            owwModel = Model(wakeword_models=[], inference_framework="onnx")
            pa = pyaudio.PyAudio()
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            CHUNK = 1280  # 80ms frames at 16kHz

            stream = pa.open(
                format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK,
            )
            logger.info("openwakeword listening...")
            while self._running:
                audio = np.frombuffer(stream.read(CHUNK, exception_on_overflow=False), dtype=np.int16)
                predictions = owwModel.predict(audio)
                for name, score in predictions.items():
                    if score > 0.5:
                        logger.info(f"Wake word detected: {name} (score={score:.2f})")
                        await self._fire()
                await asyncio.sleep(0)
        except Exception as exc:
            logger.warning(f"openwakeword loop failed: {exc}. Falling back to noop.")
            await self._loop_noop()

    async def _loop_pyaudio_keyword(self) -> None:
        """
        Lightweight keyword spotter: record short chunks, transcribe with Whisper,
        check for wake phrase. Uses existing LocalSTT if available.
        """
        try:
            import pyaudio
            import wave, tempfile, os

            RATE = 16000
            CHUNK = 1024
            RECORD_SECONDS = 2  # short clip per check
            FORMAT = pyaudio.paInt16
            CHANNELS = 1

            pa = pyaudio.PyAudio()
            stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
            logger.info("PyAudio keyword loop listening...")

            while self._running:
                frames = []
                for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
                    frames.append(stream.read(CHUNK, exception_on_overflow=False))
                    if not self._running:
                        break

                if not self._has_speech_energy(frames):
                    await asyncio.sleep(0.1)
                    continue

                # Write temp wav and transcribe
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    tmp_path = f.name
                try:
                    with wave.open(tmp_path, "wb") as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(pa.get_sample_size(FORMAT))
                        wf.setframerate(RATE)
                        wf.writeframes(b"".join(frames))

                    text = await self._transcribe(tmp_path)
                    if any(phrase in text.lower() for phrase in _WAKE_PHRASES):
                        logger.info(f"Wake phrase detected in: '{text}'")
                        await self._fire()
                finally:
                    os.unlink(tmp_path)

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            logger.info("PyAudio keyword loop interrupted during shutdown.")
            return
        except Exception as exc:
            logger.warning(f"PyAudio keyword loop failed: {exc}")
            await self._loop_noop()

    @staticmethod
    def _has_speech_energy(frames: list[bytes]) -> bool:
        for frame in frames:
            if not frame:
                continue
            try:
                if audioop.rms(frame, 2) >= _MIN_WAKE_RMS:
                    return True
            except Exception:
                continue
        return False

    async def _loop_noop(self) -> None:
        """No audio backend — detector is passive. Wake via API call only."""
        logger.info("Wake word: no audio backend. Use trigger_wake() to activate manually.")
        while self._running:
            await asyncio.sleep(5)

    async def _transcribe(self, wav_path: str) -> str:
        try:
            from core.voice.stt_engine import get_stt_engine
            result = await get_stt_engine().transcribe_async(wav_path)
            return str(result or "")
        except Exception:
            return ""

    async def _fire(self) -> None:
        if self._callback:
            try:
                await self._callback()
            except Exception as exc:
                logger.warning(f"Wake callback error: {exc}")

    async def trigger_wake(self) -> None:
        """Manually trigger wake — used from UI button or API."""
        logger.info("Wake word manually triggered")
        await self._fire()

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def running(self) -> bool:
        return self._running


_instance: WakeWordDetector | None = None


def get_wake_word_detector() -> WakeWordDetector:
    global _instance
    if _instance is None:
        _instance = WakeWordDetector()
    return _instance


__all__ = ["WakeWordDetector", "get_wake_word_detector"]
