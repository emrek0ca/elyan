"""macOS System Preferences Access"""

import asyncio
from typing import Any
from utils.logger import get_logger

logger = get_logger("macos.preferences")


async def get_system_preferences() -> dict[str, Any]:
    """Get various system preferences"""
    try:
        result = {}

        # Get computer name
        proc = await asyncio.create_subprocess_exec(
            "scutil", "--get", "ComputerName",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        result["computer_name"] = stdout.decode().strip()

        # Get time zone
        proc = await asyncio.create_subprocess_exec(
            "systemsetup", "-gettimezone",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()
        if "Time Zone:" in output:
            result["timezone"] = output.split(": ")[-1]

        # Get sleep settings using pmset
        proc = await asyncio.create_subprocess_exec(
            "pmset", "-g", "custom",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()

        # Parse display sleep
        for line in output.split("\n"):
            if "displaysleep" in line.lower():
                parts = line.strip().split()
                if len(parts) >= 2:
                    result["display_sleep_minutes"] = int(parts[1]) if parts[1].isdigit() else parts[1]
            elif "sleep" in line.lower() and "display" not in line.lower():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0].lower() == "sleep":
                    result["system_sleep_minutes"] = int(parts[1]) if parts[1].isdigit() else parts[1]

        # Get keyboard settings
        script = '''
        tell application "System Events"
            tell appearance preferences
                return dark mode
            end tell
        end tell
        '''

        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        result["dark_mode"] = stdout.decode().strip().lower() == "true"

        logger.info("Retrieved system preferences")

        return {
            "success": True,
            "preferences": result
        }

    except Exception as e:
        logger.error(f"Get preferences error: {e}")
        return {"success": False, "error": str(e)}
