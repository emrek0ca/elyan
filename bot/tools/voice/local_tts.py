import pyttsx3
import os
import platform
import asyncio
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("local_tts")

class LocalTTS:
    """Zero-cost local text-to-speech."""
    
    def __init__(self):
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
        if platform.system() == "Darwin": # macOS native is better
            os.system(f"say '{text}'")
        else:
            self.engine.say(text)
            self.engine.runAndWait()

    async def save_to_file(self, text: str, filename: str) -> str:
        """Save speech to an MP3 file."""
        output_path = Path.home() / ".elyan" / "logs" / filename
        logger.info(f"Saving speech to {output_path}")
        
        self.engine.save_to_file(text, str(output_path))
        self.engine.runAndWait()
        return str(output_path)

# Global instance
tts_engine = LocalTTS()
