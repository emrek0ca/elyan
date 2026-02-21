import os
import whisper
from typing import Optional
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("whisper_stt")

class WhisperSTT:
    def __init__(self):
        self.model_name = elyan_config.get("voice.whisper_model", "base")
        self._model = None

    def _get_model(self):
        if self._model is None:
            logger.info(f"Loading Whisper model: {self.model_name}...")
            self._model = whisper.load_model(self.model_name)
        return self._model

    async def transcribe(self, audio_path: str) -> Optional[str]:
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return None
        
        try:
            # Use thread executor for CPU-heavy model inference
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self._get_model().transcribe(audio_path))
            
            text = result.get("text", "").strip()
            logger.info(f"Transcription successful: {text[:50]}...")
            return text
        except Exception as e:
            logger.error(f"Error transcribing audio with Whisper: {e}")
            return None

# Global instance
whisper_stt = WhisperSTT()
