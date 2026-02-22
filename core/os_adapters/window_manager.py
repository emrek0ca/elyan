"""
core/os_adapters/window_manager.py
─────────────────────────────────────────────────────────────────────────────
Omni-Platform Window Mapping Adapter.
Abstracts away the OS-specific APIs so Elyan can read active window context
(BioSymbiosis) whether it's deployed on a Windows Gaming Rig, a Linux Server,
or a MacBook Pro.
"""

import sys
import subprocess
from utils.logger import get_logger

logger = get_logger("os_adapters")

def get_active_window_context() -> dict:
    """Returns {"app": app_name, "title": window_title} cross-platform."""
    if sys.platform == "darwin":
        return _get_mac_active_window()
    elif sys.platform == "win32":
        return _get_windows_active_window()
    elif sys.platform.startswith("linux"):
        return _get_linux_active_window()
    else:
        return {"app": "Unknown OS", "title": "Unsupported Platform"}

def _get_mac_active_window() -> dict:
    script = '''
    global frontApp, frontAppName, windowTitle
    set windowTitle to ""
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set frontAppName to name of frontApp
        tell process frontAppName
            tell (1st window whose value of attribute "AXMain" is true)
                set windowTitle to value of attribute "AXTitle"
            end tell
        end tell
    end tell
    return {frontAppName, windowTitle}
    '''
    try:
        result = subprocess.check_output(
            ['osascript', '-e', script], 
            stderr=subprocess.DEVNULL, timeout=2
        ).decode('utf-8').strip()
        parts = [p.strip() for p in result.split(",")]
        if len(parts) >= 2:
            return {"app": parts[0], "title": parts[1]}
        elif len(parts) == 1:
            return {"app": parts[0], "title": ""}
    except Exception:
        pass
    return {"app": "Unknown", "title": "Unknown"}

def _get_windows_active_window() -> dict:
    try:
        import win32gui
        import win32process
        import psutil
        
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        app_name = process.name()
        title = win32gui.GetWindowText(hwnd)
        return {"app": app_name, "title": title}
    except Exception as e:
        logger.debug(f"win32 api not available: {e}")
        return {"app": "win32_missing", "title": "Install pywin32+psutil"}

def _get_linux_active_window() -> dict:
    try:
        # Relies on xdotool for X11 environments
        title = subprocess.check_output(
            ['xdotool', 'getactivewindow', 'getwindowname'],
            stderr=subprocess.DEVNULL, timeout=1
        ).decode('utf-8').strip()
        
        # We can fetch process name via more xdotool hacks, returning title as both for now
        return {"app": "X11", "title": title}
    except Exception:
        return {"app": "Linux_CLI", "title": "Headless Node"}
