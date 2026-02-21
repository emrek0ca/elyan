"""
VoiceAgent - High-level voice interaction manager
Handles: Voice -> Text -> Process -> Response -> Speech
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

from core.voice.speech_to_text import get_stt_service
from core.voice.text_to_speech import get_tts_service
from core.voice.audio_utils import convert_ogg_to_wav, cleanup_temp_files
from utils.logger import get_logger

logger = get_logger("voice_agent")

class VoiceAgent:
    def __init__(self, agent):
        self.agent = agent
        self.stt = get_stt_service()
        self.tts = get_tts_service()
        self.temp_dir = Path.home() / ".elyan" / "tmp" / "voice"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def process_voice_input(self, audio_path: str, user_id: str = "local") -> Dict[str, Any]:
        """
        Process incoming audio file and return text + generated speech response.
        """
        wav_path = None
        response_audio_path = None
        start_time = time.time()
        
        try:
            # 1. Convert to WAV if needed (e.g., from web/telegram)
            if audio_path.endswith(('.ogg', '.webm', '.m4a')):
                wav_path = str(self.temp_dir / f"input_{int(time.time())}.wav")
                wav_path = convert_ogg_to_wav(audio_path, wav_path)
                if not wav_path:
                    return {"success": False, "error": "Audio conversion failed"}
            else:
                wav_path = audio_path

            # 2. Transcribe
            if not self.stt:
                return {"success": False, "error": "STT service not available"}
            
            stt_result = await self.stt.transcribe(wav_path)
            if not stt_result.get("success"):
                return stt_result
            
            user_text = stt_result.get("text", "")
            if not user_text:
                return {"success": False, "error": "No speech detected"}
            
            logger.info(f"Voice Input: {user_text}")

            # 3. Process with Agent
            response_text = await self.agent.process(user_text)
            logger.info(f"Agent Response: {response_text[:100]}...")

            # 4. Generate Speech (TTS)
            if self.tts:
                response_audio_path = str(self.temp_dir / f"response_{int(time.time())}.mp3")
                # Strip markdown for better TTS
                clean_text = self._cleanup_text_for_tts(response_text)
                await self.tts.synthesize(clean_text[:500], output_file=response_audio_path)
            
            return {
                "success": True,
                "input_text": user_text,
                "response_text": response_text,
                "response_audio": response_audio_path,
                "duration_ms": int((time.time() - start_time) * 1000)
            }

        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Clean up input wav but keep response audio for the frontend to fetch
            if wav_path and wav_path != audio_path:
                cleanup_temp_files(wav_path)

    def _cleanup_text_for_tts(self, text: str) -> str:
        """Remove markdown and special chars for cleaner speech"""
        import re
        # Remove bold/italic
        text = re.sub(r'[*_]', '', text)
        # Remove code blocks
        text = re.sub(r'```.*?```', '[Kod bloğu]', text, flags=re.DOTALL)
        # Remove URLs
        text = re.sub(r'http\S+', '[Link]', text)
        # Remove excessive punctuation
        text = re.sub(r'[#>]', '', text)
        return text.strip()

# Singleton instance helper
_voice_agent = None

def get_voice_agent(agent) -> VoiceAgent:
    global _voice_agent
    if _voice_agent is None:
        _voice_agent = VoiceAgent(agent)
    return _voice_agent
