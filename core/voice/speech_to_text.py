"""
Speech-to-Text using OpenAI Whisper (local, offline)
"""

import asyncio
import importlib
from typing import Dict, Any, Optional
from pathlib import Path
from core.dependencies import get_dependency_runtime
from utils.logger import get_logger

logger = get_logger("speech_to_text")

# Whisper imports (optional)
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    whisper = None


def _ensure_whisper_runtime() -> bool:
    global whisper, WHISPER_AVAILABLE
    if WHISPER_AVAILABLE and whisper is not None:
        return True
    try:
        import whisper as whisper_mod
        whisper = whisper_mod
        WHISPER_AVAILABLE = True
        return True
    except ImportError:
        runtime = get_dependency_runtime()
        record = runtime.ensure_module(
            "whisper",
            install_spec="openai-whisper",
            source="pypi",
            trust_level="trusted",
            skill_name="voice",
            tool_name="transcribe_audio_file",
            allow_install=True,
        )
        if record.status in {"installed", "ready"}:
            importlib.invalidate_caches()
            try:
                import whisper as whisper_mod

                whisper = whisper_mod
                WHISPER_AVAILABLE = True
                return True
            except ImportError as exc:
                runtime.ensure_from_error(
                    str(exc),
                    skill_name="voice",
                    tool_name="transcribe_audio_file",
                    allow_install=True,
                )
                try:
                    import whisper as whisper_mod

                    whisper = whisper_mod
                    WHISPER_AVAILABLE = True
                    return True
                except ImportError:
                    return False
            except Exception:
                return False
        return False


class SpeechToTextService:
    """Local speech-to-text using Whisper"""
    
    def __init__(self, model_name: str = "base"):
        """
        Initialize Whisper model.
        
        Args:
            model_name: Model size (tiny/base/small/medium/large)
                - tiny: 75MB, ~2-5s
                - base: 140MB, ~3-8s (recommended)
                - small: 460MB, ~5-15s
        """
        if not _ensure_whisper_runtime():
            logger.error("Whisper not installed. Run: pip install openai-whisper")
            self.model = None
            return
        
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load Whisper model (downloads on first run)"""
        try:
            logger.info(f"Loading Whisper model: {self.model_name}")
            self.model = whisper.load_model(self.model_name)
            logger.info(f"Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            self.model = None
    
    async def transcribe(
        self,
        audio_file: str,
        language: str = "tr",
        task: str = "transcribe"
    ) -> Dict[str, Any]:
        """
        Transcribe audio file.
        
        Args:
            audio_file: Path to WAV file
            language: Language code (tr/en/etc)
            task: 'transcribe' or 'translate'
        
        Returns:
            {
                "success": bool,
                "text": str,
                "language": str,
                "segments": list,
                "error": str (if failed)
            }
        """
        if not WHISPER_AVAILABLE or not self.model:
            return {
                "success": False,
                "error": "Whisper not available"
            }
        
        if not Path(audio_file).exists():
            return {
                "success": False,
                "error": "Audio file not found"
            }
        
        try:
            # Run Whisper in thread pool (it's CPU-bound)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._transcribe_sync,
                audio_file,
                language,
                task
            )
            
            return {
                "success": True,
                "text": result["text"].strip(),
                "language": result.get("language", language),
                "segments": result.get("segments", []),
                "duration": sum(seg.get("end", 0) - seg.get("start", 0) for seg in result.get("segments", []))
            }
        
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _transcribe_sync(self, audio_file: str, language: str, task: str) -> dict:
        """Synchronous transcription (runs in thread pool)"""
        logger.info(f"Transcribing: {audio_file} (language: {language})")
        
        result = self.model.transcribe(
            audio_file,
            language=language,
            task=task,
            fp16=False  # Use float32 for CPU
        )
        
        logger.info(f"Transcription complete: {len(result['text'])} chars")
        return result
    
    def is_available(self) -> bool:
        """Check if service is ready"""
        return WHISPER_AVAILABLE and self.model is not None


# Global singleton
_stt_service: Optional[SpeechToTextService] = None


def get_stt_service(model_name: str = "base") -> Optional[SpeechToTextService]:
    """Get singleton STT service"""
    global _stt_service
    
    if _stt_service is None:
        _stt_service = SpeechToTextService(model_name)
    
    return _stt_service if _stt_service.is_available() else None
