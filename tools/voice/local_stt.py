import os
import warnings
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("local_stt")
warnings.filterwarnings("ignore", category=UserWarning)


class LocalSTT:
    """Zero-cost local speech-to-text using OpenAI Whisper."""

    def __init__(self, model_size: str = "base"):
        self.model = None
        self.model_size = model_size
        self._whisper = None

    def _load_model(self):
        if self.model is None:
            try:
                import whisper
                self._whisper = whisper
                logger.info(f"Loading Whisper model: {self.model_size}...")
                self.model = whisper.load_model(self.model_size)
                logger.info("Whisper model loaded.")
            except ImportError:
                logger.warning("Whisper not installed. pip install openai-whisper")
            except Exception as e:
                logger.error(f"Whisper load error: {e}")

    async def transcribe(self, audio_path: str) -> str:
        """Convert audio file to text."""
        self._load_model()
        if self.model is None:
            return "[Whisper not available]"

        if not os.path.exists(audio_path):
            return ""

        logger.info(f"Transcribing {audio_path}...")
        try:
            result = self.model.transcribe(audio_path, fp16=False)
            text = result.get("text", "").strip()
            logger.info(f"Transcription complete: {text[:50]}...")
            return text
        except Exception as e:
            logger.error(f"STT Error: {e}")
            return ""


# Global instance
stt_engine = LocalSTT(model_size="base")
