"""
VoiceAgent - High-level voice interaction manager
Handles: Voice -> Text -> Process -> Response -> Speech
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import pyaudio
    HAS_AUDIO_DEPS = True
except ImportError:
    HAS_AUDIO_DEPS = False

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
        
        # Continuous listening props
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16 if HAS_AUDIO_DEPS else None
        self.CHANNELS = 1
        self.RATE = 16000
        self._running = False
        self.p_audio = pyaudio.PyAudio() if HAS_AUDIO_DEPS else None

    async def listen_loop(self):
        """Infinite loop simulating Voice Activity Detection (VAD) buffer."""
        if not HAS_AUDIO_DEPS: 
            logger.warning("pyaudio missing. Background voice loop disabled.")
            return
        
        self._running = True
        logger.info("🎙️ VoiceAgent Background Listener Started.")
        
        # Audio stream setup
        try:
            stream = self.p_audio.open(format=self.FORMAT,
                                     channels=self.CHANNELS,
                                     rate=self.RATE,
                                     input=True,
                                     frames_per_buffer=self.CHUNK)
        except Exception as e:
            logger.error(f"Microphone access failed: {e}")
            self._running = False
            return
            
        logger.info("🎙️ Listening for Voice-First reasoning...")
        
        while self._running:
            # Simulated read and VAD block. In a production pipeline:
            # 1. Accumulate chunks into a silience-delimited buffer
            # 2. Pass buffer byte array to Whisper STT
            # 3. If whisper returns text, call self._route_to_orchestrator(text)
            await asyncio.sleep(1.0)
            
        stream.stop_stream()
        stream.close()
        
    async def _route_to_orchestrator(self, text_intent: str):
        """Passes transcribed text seamlessly to the neural engine."""
        logger.info(f"🗣️ Voice Intent Triggered: {text_intent}")
        from core.multi_agent.neural_router import NeuralRouter
        from core.multi_agent.orchestrator import AgentOrchestrator
        
        try:
            router = NeuralRouter(self.agent)
            template = await router.route_request(text_intent)
            orchestrator = AgentOrchestrator(self.agent)
            
            # Fire and forget execution to keep voice loop unblocked
            asyncio.create_task(orchestrator.manage_flow(template, text_intent))
            
            if self.tts:
               await self.tts.synthesize("Komut alındı, uyguluyorum.", output_file=str(self.temp_dir / "ack.mp3"))
        except Exception as e:
            logger.error(f"Voice to Orchestrator fail: {e}")
            
    def stop(self):
        self._running = False
        if self.p_audio:
            self.p_audio.terminate()
        logger.info("🛑 VoiceAgent offline.")

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
            from core.security.ingress_guard import blocked_ingress_text, inspect_ingress

            verdict = await inspect_ingress(
                user_text,
                platform_origin="voice_local",
                agent=self.agent,
                metadata={"user_id": str(user_id or "local"), "channel_type": "voice_local"},
            )
            if not verdict.get("allowed", True):
                return {
                    "success": False,
                    "input_text": user_text,
                    "error": "voice_request_blocked",
                    "response_text": blocked_ingress_text(verdict),
                }

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
