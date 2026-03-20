import importlib
import os
from typing import Optional

from core.dependencies import get_dependency_runtime
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("whisper_stt")

try:
    import whisper
except ImportError:
    runtime = get_dependency_runtime()
    record = runtime.ensure_module(
        "whisper",
        install_spec="openai-whisper",
        source="pypi",
        trust_level="trusted",
        skill_name="voice",
        tool_name="whisper_stt",
        allow_install=True,
    )
    if record.status in {"installed", "ready"}:
        importlib.invalidate_caches()
        try:
            import whisper
        except ImportError as exc:
            runtime.ensure_from_error(
                str(exc),
                skill_name="voice",
                tool_name="whisper_stt",
                allow_install=True,
            )
            importlib.invalidate_caches()
            try:
                import whisper
            except ImportError:
                whisper = None
    else:
        whisper = None

class WhisperSTT:
    def __init__(self):
        self.model_name = elyan_config.get("voice.whisper_model", "base")
        self._model = None

    def _get_model(self):
        if self._model is None:
            if whisper is None:
                return None
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
            model = self._get_model()
            if model is None:
                return None
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: model.transcribe(audio_path))
            
            text = result.get("text", "").strip()
            logger.info(f"Transcription successful: {text[:50]}...")
            return text
        except Exception as e:
            logger.error(f"Error transcribing audio with Whisper: {e}")
            return None

# Global instance
whisper_stt = WhisperSTT()
