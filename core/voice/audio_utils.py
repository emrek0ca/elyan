"""
Audio utilities for voice processing

Handles:
- Audio format conversion (OGG/OPUS → WAV)
- File validation
- Temp file management
"""

import subprocess
import os
from pathlib import Path
from typing import Optional, Tuple
from utils.logger import get_logger

logger = get_logger("audio_utils")


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def convert_ogg_to_wav(ogg_path: str, wav_path: Optional[str] = None) -> Optional[str]:
    """
    Convert OGG/OPUS to WAV using FFmpeg.
    
    Args:
        ogg_path: Input OGG file path
        wav_path: Output WAV file path (auto-generated if None)
    
    Returns:
        Path to WAV file or None if failed
    """
    if not check_ffmpeg():
        logger.error("FFmpeg not found. Install: brew install ffmpeg")
        return None
    
    if wav_path is None:
        wav_path = str(Path(ogg_path).with_suffix('.wav'))
    
    try:
        # Convert with FFmpeg
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-i', ogg_path,
            '-ar', '16000',  # 16kHz (Whisper requirement)
            '-ac', '1',  # Mono
            '-c:a', 'pcm_s16le',  # WAV format
            wav_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg conversion failed: {result.stderr}")
            return None
        
        if not os.path.exists(wav_path):
            logger.error("WAV file not created")
            return None
        
        logger.info(f"Converted: {ogg_path} → {wav_path}")
        return wav_path
    
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout")
        return None
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        return None


def get_audio_duration(file_path: str) -> Optional[float]:
    """Get audio duration in seconds"""
    if not check_ffmpeg():
        return None
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return float(result.stdout.strip())
    except:
        pass
    
    return None


def cleanup_temp_files(*file_paths: str):
    """Delete temporary audio files"""
    for path in file_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
                logger.debug(f"Deleted temp file: {path}")
        except Exception as e:
            logger.warning(f"Failed to delete {path}: {e}")


def validate_audio_file(file_path: str, max_size_mb: int = 20) -> Tuple[bool, str]:
    """
    Validate audio file.
    
    Returns:
        (is_valid, error_message)
    """
    if not os.path.exists(file_path):
        return False, "File not found"
    
    # Check size
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > max_size_mb:
        return False, f"File too large ({size_mb:.1f}MB > {max_size_mb}MB)"
    
    # Check duration (if possible)
    duration = get_audio_duration(file_path)
    if duration and duration > 300:  # 5 minutes
        return False, f"Audio too long ({duration:.0f}s > 300s)"
    
    return True, ""
