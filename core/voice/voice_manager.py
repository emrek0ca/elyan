from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from typing import Any, Optional

from config.elyan_config import elyan_config
from tools.voice.wake_word import WakeWordDetector
from core.voice.speech_to_text import get_stt_service
from core.voice.text_to_speech import get_tts_service
from utils.logger import get_logger

logger = get_logger("voice_manager")


class VoiceManager:
    """Lightweight voice runtime manager for CLI and gateway status."""

    def __init__(self) -> None:
        self.running = False
        self.started_at: Optional[str] = None
        self.stt = None
        self.tts = None
        self.wake_word = str(elyan_config.get("voice.wake_word", "elyan") or "elyan")
        self._wake_detector = WakeWordDetector(callback=self._on_wake_word)
        self._wake_task: Optional[asyncio.Task[Any]] = None

    async def _on_wake_word(self):
        logger.info("Wake word detected.")
        if self.tts:
            try:
                await self.tts.synthesize("Komut alındı.")
            except Exception as exc:
                logger.debug(f"Wake word ack failed: {exc}")

    async def start(self) -> dict[str, Any]:
        if self.running:
            return self.get_status()
        self.stt = get_stt_service()
        self.tts = get_tts_service()
        self.running = True
        self.started_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            self._wake_task = asyncio.create_task(self._wake_detector.start())
        except Exception as exc:
            logger.debug(f"Wake word task not started: {exc}")
            self._wake_task = None
        return self.get_status()

    async def stop(self) -> dict[str, Any]:
        self.running = False
        try:
            await self._wake_detector.stop()
        except Exception as exc:
            logger.debug(f"Wake word stop failed: {exc}")
        if self._wake_task:
            self._wake_task.cancel()
            try:
                await self._wake_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._wake_task = None
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        return {
            "running": bool(self.running),
            "started_at": self.started_at or "",
            "stt_provider": "whisper" if self.stt else "unavailable",
            "tts_provider": "pyttsx3" if self.tts else "unavailable",
            "wake_word": self.wake_word,
            "wake_word_listener": bool(self._wake_task and not self._wake_task.done()),
        }


_voice_manager: Optional[VoiceManager] = None


def get_voice_manager() -> VoiceManager:
    global _voice_manager
    if _voice_manager is None:
        _voice_manager = VoiceManager()
    return _voice_manager
