import subprocess
import time
import os
from pathlib import Path

def record_screen(duration_seconds: int = 10, filename: str = "screen_recording.mp4") -> str:
    """
    Record the screen for a specified duration using ffmpeg.
    Works on macOS using avfoundation.
    """
    try:
        duration_seconds = int(duration_seconds)
        if duration_seconds > 60:
            return "Error: Maximum recording duration is 60 seconds."
            
        output_path = Path.home() / "Desktop" / filename
        if output_path.exists():
            base, ext = os.path.splitext(filename)
            timestamp = int(time.time())
            output_path = Path.home() / "Desktop" / f"{base}_{timestamp}{ext}"

        # ffmpeg command for macOS screen capture
        # -f avfoundation -i "1" (screen 1) -t duration
        command = [
            "ffmpeg",
            "-y", # Overwrite output files
            "-f", "avfoundation",
            "-i", "1", # Capture screen 1
            "-t", str(duration_seconds),
            "-r", "30", # 30 fps
            str(output_path)
        ]

        print(f"Recording screen for {duration_seconds} seconds...")
        # Run ffmpeg
        process = subprocess.run(command, capture_output=True, text=True)
        
        if process.returncode == 0:
            return f"Screen recording saved to {output_path}"
        else:
            # Check if it's a permission issue or device index issue
            if "AuthorizationStatus" in process.stderr or "not found" in process.stderr:
                return f"Error: Screen recording failed. Ensure terminal has Screen Recording permission. Details: {process.stderr[:200]}"
            return f"Error recording screen: {process.stderr[:200]}"

    except Exception as e:
        return f"Error executing screen recording: {e}"
