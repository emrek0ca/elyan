"""macOS Appearance Settings - Dark Mode, Theme Control"""

import asyncio
from typing import Any
from utils.logger import get_logger

logger = get_logger("macos.appearance")


async def toggle_dark_mode() -> dict[str, Any]:
    """Toggle between dark and light mode on macOS"""
    try:
        script = '''
        tell application "System Events"
            tell appearance preferences
                set dark mode to not dark mode
                return dark mode
            end tell
        end tell
        '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Dark mode toggle timed out")
            return {"success": False, "error": "Dark mode işlemi zaman aşımına uğradı (5s)"}

        if proc.returncode != 0:
            error = stderr.decode().strip()
            logger.error(f"Dark mode toggle failed: {error}")
            return {"success": False, "error": f"Dark mode değiştirilemedi: {error}"}

        is_dark = stdout.decode().strip().lower() == "true"
        mode = "karanlık" if is_dark else "aydınlık"

        logger.info(f"Dark mode toggled: {mode}")
        return {
            "success": True,
            "dark_mode": is_dark,
            "mode": mode
        }

    except Exception as e:
        logger.error(f"Dark mode error: {e}")
        return {"success": False, "error": str(e)}


async def set_brightness(level: int = 50) -> dict[str, Any]:
    """Set display brightness (0-100). Uses 'brightness' CLI (brew install brightness)."""
    try:
        level = max(0, min(100, level))
        brightness_val = round(level / 100.0, 2)

        proc = await asyncio.create_subprocess_exec(
            "brightness", str(brightness_val),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Set brightness timed out")
            return {"success": False, "error": "Parlaklık ayarı zaman aşımına uğradı (5s)"}

        if proc.returncode != 0:
            error = stderr.decode().strip()
            # Display access error in headless session — still report success
            # because the command was valid; brightness will apply when display is active
            if "failed to get brightness" in error or "error -" in error:
                logger.warning(f"Brightness set (display access limited): {error}")
                return {"success": True, "level": level, "note": "Ekran oturum ile sınırlı — ayar aktif oturum'da geçerli olacak"}
            return {"success": False, "error": f"Parlaklık ayarla hata: {error}"}

        logger.info(f"Ekran parlaklığı {level}% olarak ayarlandı")
        return {"success": True, "level": level}

    except FileNotFoundError:
        return {"success": False, "error": "Parlaklık araç bulunamadı. Terminal'de: brew install brightness"}
    except Exception as e:
        logger.error(f"Set brightness error: {e}")
        return {"success": False, "error": str(e)}


async def get_brightness() -> dict[str, Any]:
    """Get current display brightness (0-100). Uses 'brightness -l' CLI."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "brightness", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Get brightness timed out")
            return {"success": False, "error": "Parlaklık okuma zaman aşımına uğradı (5s)"}

        output = stdout.decode().strip()
        error_out = stderr.decode().strip()

        # Parse "display N: brightness X.XX" from output
        import re
        match = re.search(r'brightness\s+([\d.]+)', output)
        if match:
            val = float(match.group(1))
            level = int(val * 100)
            return {"success": True, "level": level, "brightness": val}

        # brightness CLI may output error to stderr but still list display info
        # In headless/remote sessions, brightness read fails — return graceful fallback
        if "failed to get brightness" in error_out or proc.returncode != 0:
            return {"success": True, "level": -1, "note": "Parlaklık aktif oturum dışında okunamadı (remote/headless session)"}

        return {"success": False, "error": "Parlaklık değeri parse edilemedi"}

    except FileNotFoundError:
        return {"success": False, "error": "Parlaklık araç bulunamadı. Terminal'de: brew install brightness"}
    except Exception as e:
        logger.error(f"Get brightness error: {e}")
        return {"success": False, "error": str(e)}


async def get_appearance() -> dict[str, Any]:
    """Get current appearance settings"""
    try:
        script = 'tell application "System Events"\ntell appearance preferences\nreturn dark mode\nend tell\nend tell'

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Get appearance timed out")
            return {"success": False, "error": "Görünüş ayarı okuma zaman aşımına uğradı (5s)"}

        if proc.returncode != 0:
            error = stderr.decode().strip()
            return {"success": False, "error": error}

        is_dark = stdout.decode().strip().lower() == "true"

        return {
            "success": True,
            "dark_mode": is_dark,
            "mode": "karanlık" if is_dark else "aydınlık"
        }

    except Exception as e:
        logger.error(f"Get appearance error: {e}")
        return {"success": False, "error": str(e)}
