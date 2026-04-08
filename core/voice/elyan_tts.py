"""
core/voice/elyan_tts.py
───────────────────────────────────────────────────────────────────────────────
ElyanTTS — Text-to-Speech for Elyan Elyan

Backends (graceful degradation):
  1. macOS `say` command    — always available, zero deps, good quality
  2. pyttsx3                — cross-platform, offline
  3. ElevenLabs API         — high quality, requires API key
  4. Silent fallback        — logs only, never crashes

Voice profile: calm, clear, professional. Rate ~180wpm.
"""
from __future__ import annotations

import asyncio
import shlex
from utils.logger import get_logger

logger = get_logger("elyan_tts")

# macOS `say` voice — change to preferred voice
_MACOS_VOICE = "Siri (English (United States))"   # fallback: "Alex" or "Samantha"
_MACOS_RATE = 185  # words per minute


class ElyanTTS:
    """
    Async TTS engine with macOS-native backend.

    Usage:
        tts = get_elyan_tts()
        await tts.speak("Task completed successfully.")
    """

    def __init__(self) -> None:
        self._backend: str = self._detect_backend()
        self._enabled: bool = True
        logger.info(f"ElyanTTS ready (backend: {self._backend})")

    @staticmethod
    def _detect_backend() -> str:
        import shutil
        if shutil.which("say"):
            return "macos_say"
        try:
            import pyttsx3  # noqa: F401
            return "pyttsx3"
        except ImportError:
            pass
        return "silent"

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    async def speak(self, text: str, *, interrupt: bool = False) -> bool:
        """
        Speak text aloud.

        Args:
            text:      Text to speak.
            interrupt: If True, kill any ongoing speech before starting.

        Returns:
            True on success, False on failure.
        """
        if not self._enabled or not text.strip():
            return False

        clean = self._clean_text(text)

        if self._backend == "macos_say":
            return await self._speak_macos(clean, interrupt)
        if self._backend == "pyttsx3":
            return await self._speak_pyttsx3(clean)
        # silent
        logger.debug(f"TTS (silent): {clean[:80]}")
        return True

    async def _speak_macos(self, text: str, interrupt: bool) -> bool:
        """Use macOS `say` command."""
        if interrupt:
            # Kill any running `say` process
            await asyncio.create_subprocess_exec(
                "killall", "say",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                "say",
                "-r", str(_MACOS_RATE),
                text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=60.0)
            return proc.returncode == 0
        except asyncio.TimeoutError:
            logger.warning("TTS timeout — killing say process")
            try:
                proc.kill()
            except Exception:
                pass
            return False
        except Exception as exc:
            logger.warning(f"TTS macos_say error: {exc}")
            return False

    async def _speak_pyttsx3(self, text: str) -> bool:
        """Use pyttsx3 (cross-platform)."""
        try:
            import pyttsx3
            loop = asyncio.get_event_loop()

            def _blocking_speak():
                engine = pyttsx3.init()
                engine.setProperty("rate", _MACOS_RATE)
                engine.say(text)
                engine.runAndWait()

            await loop.run_in_executor(None, _blocking_speak)
            return True
        except Exception as exc:
            logger.warning(f"TTS pyttsx3 error: {exc}")
            return False

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip markdown and control chars for clean speech."""
        import re
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"`(.*?)`", r"\1", text)
        text = re.sub(r"#{1,6}\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        text = re.sub(r"[^\w\s.,!?;:\-\(\)\'\"üğışöçÜĞİŞÖÇ]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]  # safety cap


_instance: ElyanTTS | None = None


def get_elyan_tts() -> ElyanTTS:
    global _instance
    if _instance is None:
        _instance = ElyanTTS()
    return _instance


__all__ = ["ElyanTTS", "get_elyan_tts"]
