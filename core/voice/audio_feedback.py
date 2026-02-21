"""
Audio Feedback Module
Provides simple sound cues for success, error, and notification events.
Designed to be non-intrusive and platform-agnostic (fallback to system sounds).
"""

import sys
import subprocess
import os
from pathlib import Path
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("audio_feedback")

class AudioFeedbackEngine:
    def __init__(self):
        self.platform = sys.platform
        self._enabled = elyan_config.get("voice.feedback_enabled", True)
        
    def play_success(self):
        """Play a subtle success sound."""
        if not self._should_play(): return
        self._play_system_sound("Glass") # macOS default

    def play_error(self):
        """Play an error sound."""
        if not self._should_play(): return
        self._play_system_sound("Basso") # macOS default

    def play_notification(self):
        """Play a notification/attention sound."""
        if not self._should_play(): return
        self._play_system_sound("Tink") # macOS default

    def _should_play(self) -> bool:
        # Reload config to allow runtime toggle
        return bool(elyan_config.get("voice.feedback_enabled", True))

    def _play_system_sound(self, sound_name: str):
        """Play a system sound by name (macOS)."""
        if self.platform != "darwin":
            return # TODO: Add Linux/Windows support (paplay, winsound)
            
        try:
            # Look for sound in standard paths
            paths = [
                f"/System/Library/Sounds/{sound_name}.aiff",
                f"/System/Library/Sounds/{sound_name}.m4a",
                f"/System/Library/Sounds/{sound_name}.wav"
            ]
            
            sound_path = None
            for p in paths:
                if os.path.exists(p):
                    sound_path = p
                    break
            
            if sound_path:
                # Run in background, don't block
                subprocess.Popen(["afplay", sound_path], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            else:
                logger.debug(f"Sound not found: {sound_name}")
                
        except Exception as e:
            logger.debug(f"Failed to play sound: {e}")

# Singleton
_audio_feedback = AudioFeedbackEngine()

def get_audio_feedback() -> AudioFeedbackEngine:
    return _audio_feedback
