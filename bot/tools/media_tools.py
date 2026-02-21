import asyncio
from typing import Dict, Any, Optional
from .terminal_tools import execute_safe_command

async def control_music(action: str, app: str = "Music") -> Dict[str, Any]:
    """Control Music.app or Spotify (play, pause, next, previous)"""
    valid_actions = {
        "play": "play",
        "pause": "pause",
        "stop": "pause",
        "next": "next track",
        "previous": "previous track",
        "resume": "play"
    }
    
    if action.lower() not in valid_actions:
        return {"success": False, "error": f"Geçersiz işlem: {action}"}
        
    actual_action = valid_actions[action.lower()]
    app_target = "Music" if "music" in app.lower() else "Spotify"
    
    script = f'tell application "{app_target}" to {actual_action}'
    result = await execute_safe_command(f"osascript -e '{script}'")
    
    if result["success"]:
        return {"success": True, "message": f"{app_target} işlemi tamamlandı: {action}"}
    return {"success": False, "error": f"{app_target} kontrol edilemedi"}

async def get_now_playing() -> Dict[str, Any]:
    """Get currently playing track info from Music.app or Spotify"""
    # Music.app script
    music_script = 'tell application "Music" to if it is running then get {name, artist} of current track'
    # Spotify script
    spotify_script = 'tell application "Spotify" to if it is running then get {name, artist} of current track'
    
    # Try Music.app first
    result = await execute_safe_command(f"osascript -e '{music_script}'")
    if result["success"] and result["output"].strip():
        parts = result["output"].strip().split(", ")
        if len(parts) >= 2:
            return {
                "success": True, 
                "app": "Music",
                "track": parts[0],
                "artist": parts[1],
                "message": f"Şu an çalıyor (Music): {parts[0]} - {parts[1]}"
            }
            
    # Try Spotify
    result = await execute_safe_command(f"osascript -e '{spotify_script}'")
    if result["success"] and result["output"].strip():
        parts = result["output"].strip().split(", ")
        if len(parts) >= 2:
            return {
                "success": True, 
                "app": "Spotify",
                "track": parts[0],
                "artist": parts[1],
                "message": f"Şu an çalıyor (Spotify): {parts[0]} - {parts[1]}"
            }
            
    return {"success": False, "error": "Çalan bir parça bulunamadı"}

async def set_display_brightness(level: int) -> Dict[str, Any]:
    """Adjust system brightness (0-100)"""
    level = max(0, min(100, level))
    # Note: Requires 'brightness' utility to be installed via brew, 
    # or we can use applescript for basic control.
    # Fallback applescript (doesn't work on all macOS versions/displays easily)
    script = f'tell application "System Events" to repeat {int(level/6)} times \n key code 144 \n end repeat'
    # However, 'brightness' CLI is better if whitelisted.
    # Let's try the 'brightness' command first
    res = await execute_safe_command(f"brightness {level/100}")
    if res["success"]:
        return {"success": True, "level": level, "message": f"Parlaklık %{level} yapıldı"}
        
    return {"success": False, "error": "Parlaklık ayarlanamadı (brightness CLI yüklü olmayabilir)"}
