"""
Text-to-Speech using pyttsx3 (local, offline)
"""

import asyncio
from typing import Optional
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("text_to_speech")

# pyttsx3 imports (optional)
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    pyttsx3 = None


class TextToSpeechService:
    """Local text-to-speech using pyttsx3 (macOS NSSpeech)"""
    
    def __init__(self):
        if not TTS_AVAILABLE:
            logger.error("pyttsx3 not installed. Run: pip install pyttsx3")
            self.engine = None
            return
        
        try:
            self.engine = pyttsx3.init()
            self._configure_voice()
            logger.info("TTS engine initialized")
        except Exception as e:
            logger.error(f"TTS init failed: {e}")
            self.engine = None
    
    def _configure_voice(self):
        """Configure voice settings"""
        if not self.engine:
            return
        
        try:
            # Get available voices
            voices = self.engine.getProperty('voices')
            
            # Try to find Turkish voice (macOS)
            turkish_voice = None
            for voice in voices:
                if 'turkish' in voice.name.lower() or 'tr-tr' in voice.id.lower():
                    turkish_voice = voice.id
                    break
            
            if turkish_voice:
                self.engine.setProperty('voice', turkish_voice)
                logger.info(f"Using Turkish voice")
            
            # Set rate (speed)
            self.engine.setProperty('rate', 175)  # Default: 200
            
            # Set volume
            self.engine.setProperty('volume', 0.9)
        
        except Exception as e:
            logger.warning(f"Voice config failed: {e}")
    
    async def synthesize(self, text: str, output_file: Optional[str] = None) -> bool:
        """
        Synthesize text to speech.
        
        Args:
            text: Text to speak
            output_file: Optional audio file path to save
        
        Returns:
            True if successful
        """
        if not TTS_AVAILABLE or not self.engine:
            return False
        
        try:
            # Run in executor (pyttsx3 is blocking)
            loop = asyncio.get_event_loop()
            
            if output_file:
                # Save to file
                await loop.run_in_executor(
                    None,
                    self._synthesize_to_file,
                    text,
                    output_file
                )
            else:
                # Just speak (no output)
                await loop.run_in_executor(
                    None,
                    self._synthesize_sync,
                    text
                )
            
            return True
        
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return False
    
    def _synthesize_sync(self, text: str):
        """Synchronous speech synthesis"""
        self.engine.say(text)
        self.engine.runAndWait()
    
    def _synthesize_to_file(self, text: str, output_file: str):
        """Synchronous synthesis to file"""
        self.engine.save_to_file(text, output_file)
        self.engine.runAndWait()
    
    def is_available(self) -> bool:
        """Check if TTS is ready"""
        return TTS_AVAILABLE and self.engine is not None


# Global singleton
_tts_service: Optional[TextToSpeechService] = None


def get_tts_service() -> Optional[TextToSpeechService]:
    """Get singleton TTS service"""
    global _tts_service
    
    if _tts_service is None:
        _tts_service = TextToSpeechService()
    
    return _tts_service if _tts_service.is_available() else None
