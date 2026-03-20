import importlib
import os
import platform
import asyncio
from pathlib import Path
from core.dependencies import get_dependency_runtime
from utils.logger import get_logger

logger = get_logger("local_tts")

try:
    import pyttsx3
except ImportError:
    runtime = get_dependency_runtime()
    record = runtime.ensure_module(
        "pyttsx3",
        install_spec="pyttsx3",
        source="pypi",
        trust_level="trusted",
        skill_name="voice",
        tool_name="local_tts",
        allow_install=True,
    )
    if record.status in {"installed", "ready"}:
        importlib.invalidate_caches()
        import pyttsx3
    else:
        pyttsx3 = None

class LocalTTS:
    """Zero-cost local text-to-speech."""
    
    def __init__(self):
        if pyttsx3 is None:
            self.engine = None
            return
        self.engine = pyttsx3.init()
        self._setup_voice()

    def _setup_voice(self):
        voices = self.engine.getProperty('voices')
        # Try to find a Turkish voice if possible, otherwise use default
        for voice in voices:
            if "TR" in voice.id or "Turkish" in voice.name:
                self.engine.setProperty('voice', voice.id)
                break
        self.engine.setProperty('rate', 175) # Speed

    async def speak(self, text: str):
        """Play voice immediately."""
        logger.info(f"Speaking: {text[:50]}...")
        if self.engine is None:
            return
        if platform.system() == "Darwin": # macOS native is better
            os.system(f"say '{text}'")
        else:
            self.engine.say(text)
            self.engine.runAndWait()

    async def save_to_file(self, text: str, filename: str) -> str:
        """Save speech to an MP3 file."""
        output_path = Path.home() / ".elyan" / "logs" / filename
        logger.info(f"Saving speech to {output_path}")
        if self.engine is None:
            return str(output_path)
        
        self.engine.save_to_file(text, str(output_path))
        self.engine.runAndWait()
        return str(output_path)

# Global instance
tts_engine = LocalTTS()
