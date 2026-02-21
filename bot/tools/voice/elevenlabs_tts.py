import os
from typing import Optional
from elevenlabs.client import ElevenLabs
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("elevenlabs_tts")

class ElevenLabsTTS:
    def __init__(self):
        self.api_key = elyan_config.get("voice.elevenlabs_api_key") or os.getenv("ELEVENLABS_API_KEY")
        self.client = ElevenLabs(api_key=self.api_key) if self.api_key else None
        self.voice_id = elyan_config.get("voice.voice_id", "pNInz6obpg8nEByWQX7d") # Default Adam voice

    async def generate_audio(self, text: str, output_path: str) -> bool:
        if not self.client:
            logger.error("ElevenLabs API key missing.")
            return False
        
        try:
            audio = self.client.generate(
                text=text,
                voice=self.voice_id,
                model="eleven_multilingual_v2"
            )
            
            with open(output_path, "wb") as f:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Audio generated and saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error generating audio with ElevenLabs: {e}")
            return False

# Global instance
elevenlabs_tts = ElevenLabsTTS()
