import asyncio
from utils.logger import get_logger

logger = get_logger("wake_word")

class WakeWordDetector:
    """
    macOS Wake Word Detector using system frameworks via pyobjc.
    Simplified for demo/integration purposes.
    """
    def __init__(self, callback=None):
        self.callback = callback
        self.is_listening = False

    async def start(self):
        self.is_listening = True
        logger.info("Wake word detector started (listening for 'Hey Elyan')...")
        
        # In a real implementation, we would use SFSpeechRecognizer on macOS
        # For now, we mock the detection or wait for a specific signal
        while self.is_listening:
            # Simulation of waiting for wake word
            await asyncio.sleep(10)
            # If detected:
            # if self.callback: await self.callback()

    async def stop(self):
        self.is_listening = False
        logger.info("Wake word detector stopped.")

# Global instance
wake_word_detector = WakeWordDetector()
