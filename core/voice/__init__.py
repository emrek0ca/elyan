"""
Voice module for Elyan

Provides speech-to-text and text-to-speech capabilities
"""

from .audio_utils import (
    check_ffmpeg,
    convert_ogg_to_wav,
    get_audio_duration,
    cleanup_temp_files,
    validate_audio_file
)

from .speech_to_text import (
    SpeechToTextService,
    get_stt_service,
    WHISPER_AVAILABLE
)

from .text_to_speech import (
    TextToSpeechService,
    get_tts_service,
    TTS_AVAILABLE
)
from .voice_manager import (
    VoiceManager,
    get_voice_manager,
)

__all__ = [
    # Audio utils
    'check_ffmpeg',
    'convert_ogg_to_wav',
    'get_audio_duration',
    'cleanup_temp_files',
    'validate_audio_file',
    
    # STT
    'SpeechToTextService',
    'get_stt_service',
    'WHISPER_AVAILABLE',
    
    # TTS
    'TextToSpeechService',
    'get_tts_service',
    'TTS_AVAILABLE',
    
    # Voice manager
    'VoiceManager',
    'get_voice_manager',
]
