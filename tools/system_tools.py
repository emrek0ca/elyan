import asyncio
import platform
import subprocess
import os
import time
from pathlib import Path
from typing import Any, Optional, Dict, List
from core.registry import tool
from utils.logger import get_logger

logger = get_logger("system_tools")

async def _run_osascript(script: str) -> tuple[int, str, str]:
    """Helper to run AppleScript commands."""
    process = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="ignore").strip(),
        stderr.decode("utf-8", errors="ignore").strip(),
    )

# --- SYSTEM INFORMATION ---

@tool("get_system_info", "Retrieve CPU, RAM, Disk and OS information.")
async def get_system_info() -> dict[str, Any]:
    try:
        # CPU
        cpu_cmd = "top -l 1 | grep 'CPU usage' | awk '{print $3}' | tr -d '%'"
        cpu_proc = await asyncio.create_subprocess_shell(cpu_cmd, stdout=asyncio.subprocess.PIPE)
        cpu_out, _ = await cpu_proc.communicate()
        cpu_percent = float(cpu_out.decode().strip() or 0.0)

        # Memory
        mem_total_proc = await asyncio.create_subprocess_shell("sysctl -n hw.memsize", stdout=asyncio.subprocess.PIPE)
        mem_total_out, _ = await mem_total_proc.communicate()
        total_gb = round(int(mem_total_out.decode().strip() or 0) / (1024**3), 2)

        # Disk
        disk_proc = await asyncio.create_subprocess_shell("df -h / | tail -1 | awk '{print $5}'", stdout=asyncio.subprocess.PIPE)
        disk_out, _ = await disk_proc.communicate()
        disk_usage = disk_out.decode().strip()

        return {
            "success": True,
            "system": {
                "os": platform.system(),
                "version": platform.mac_ver()[0] if platform.system() == "Darwin" else platform.version(),
                "hostname": platform.node()
            },
            "cpu": {"percent": cpu_percent},
            "memory": {"total_gb": total_gb},
            "disk": {"usage": disk_usage},
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"System info error: {e}")
        return {"success": False, "error": str(e)}

@tool("get_battery_status", "Get battery percentage and charging status.")
async def get_battery_status() -> dict[str, Any]:
    try:
        if platform.system() != "Darwin":
            return {"success": False, "error": "Battery check only supported on macOS."}
            
        script = 'do shell script "pmset -g batt"'
        _, out, _ = await _run_osascript(script)
        # Parse output like: "Now drawing from 'Battery Power'; -InternalBattery-0 (id=123) 95%; ..."
        import re
        pct_match = re.search(r"(\d+)%", out)
        charging = "AC Power" in out or "charging" in out
        
        return {
            "success": True,
            "percent": int(pct_match.group(1)) if pct_match else 0,
            "is_charging": charging
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- APP & PROCESS CONTROL ---

@tool("open_app", "Launch a desktop application.")
async def open_app(app_name: Optional[str] = None) -> dict[str, Any]:
    try:
        if not app_name or not str(app_name).strip():
            return {
                "success": False,
                "error": "app_name gerekli (örnek: Safari, Google Chrome, Finder)."
            }
        app_name = str(app_name).strip()
        process = await asyncio.create_subprocess_exec("open", "-a", app_name)
        await process.wait()
        return {"success": True, "message": f"{app_name} opened."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("close_app", "Quit a running application.")
async def close_app(app_name: Optional[str] = None) -> dict[str, Any]:
    try:
        if not app_name or not str(app_name).strip():
            return {
                "success": False,
                "error": "app_name gerekli (örnek: Safari, Google Chrome, Finder)."
            }
        app_name = str(app_name).strip()
        script = f'tell application "{app_name}" to quit'
        code, _, _ = await _run_osascript(script)
        return {"success": code == 0, "message": f"{app_name} closed."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("kill_process", "Forcefully terminate a process by name or PID.")
async def kill_process(process_name: str) -> dict[str, Any]:
    try:
        cmd = ["pkill", "-f", process_name]
        process = await asyncio.create_subprocess_exec(*cmd)
        await process.wait()
        return {"success": True, "message": f"Process {process_name} killed."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("get_running_apps", "List all active non-background applications.")
async def get_running_apps() -> dict[str, Any]:
    try:
        script = 'tell application "System Events" to get name of every process whose background only is false'
        code, out, _ = await _run_osascript(script)
        apps = [app.strip() for app in out.split(",")] if out else []
        return {"success": code == 0, "apps": apps, "count": len(apps)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("get_process_info", "Search for specific process details.")
async def get_process_info(process_name: str) -> dict[str, Any]:
    try:
        cmd = f"ps aux | grep -i '{process_name}' | grep -v grep"
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        lines = out.decode().strip().split('\n')
        return {"success": True, "count": len(lines) if out else 0, "details": lines}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- MEDIA & INPUT ---

@tool("set_volume", "Change system volume (0-100).")
async def set_volume(level: int) -> dict[str, Any]:
    try:
        level = max(0, min(100, level))
        await asyncio.create_subprocess_exec("osascript", "-e", f"set volume output volume {level}")
        return {"success": True, "level": level}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("set_brightness", "Change screen brightness (0-100).")
async def set_brightness(level: int) -> dict[str, Any]:
    try:
        # Requires 'brightness' tool from Homebrew usually
        val = level / 100.0
        await asyncio.create_subprocess_shell(f"brightness {val}")
        return {"success": True, "level": level}
    except Exception:
        return {"success": False, "error": "CLI tool 'brightness' not found. Install with brew."}

@tool("toggle_dark_mode", "Toggle between Light and Dark mode.")
async def toggle_dark_mode() -> dict[str, Any]:
    try:
        script = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'
        await _run_osascript(script)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("read_clipboard", "Get current text from clipboard.")
async def read_clipboard() -> dict[str, Any]:
    try:
        p = await asyncio.create_subprocess_exec("pbpaste", stdout=asyncio.subprocess.PIPE)
        out, _ = await p.communicate()
        return {"success": True, "text": out.decode().strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("write_clipboard", "Copy text to clipboard.")
async def write_clipboard(text: str) -> dict[str, Any]:
    try:
        p = await asyncio.create_subprocess_exec("pbcopy", stdin=asyncio.subprocess.PIPE)
        await p.communicate(input=text.encode())
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- UTILITIES ---

@tool("take_screenshot", "Capture screen and save to Desktop.")
async def take_screenshot(filename: Optional[str] = None) -> dict[str, Any]:
    try:
        path = Path.home() / "Desktop" / (filename or f"SS_{int(time.time())}.png")
        await asyncio.create_subprocess_exec("screencapture", "-x", str(path))
        return {"success": True, "path": str(path)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("send_notification", "Display a system notification.")
async def send_notification(title: str, message: str) -> dict[str, Any]:
    try:
        script = f'display notification "{message}" with title "{title}"'
        await _run_osascript(script)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("open_url", "Open a website in default browser.")
async def open_url(url: str) -> dict[str, Any]:
    try:
        if not url.startswith("http"): url = "https://" + url
        await asyncio.create_subprocess_exec("open", url)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("shutdown_system", "Initiate system shutdown.")
async def shutdown_system() -> dict[str, Any]:
    try:
        await _run_osascript('tell application "System Events" to shut down')
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("restart_system", "Initiate system restart.")
async def restart_system() -> dict[str, Any]:
    try:
        await _run_osascript('tell application "System Events" to restart')
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("sleep_system", "Put system to sleep.")
async def sleep_system() -> dict[str, Any]:
    try:
        await _run_osascript('tell application "System Events" to sleep')
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("lock_screen", "Lock the current session.")
async def lock_screen() -> dict[str, Any]:
    try:
        cmd = "/System/Library/CoreServices/Menu\\ Extras/User.menu/Contents/Resources/CGSession -suspend"
        await asyncio.create_subprocess_shell(cmd)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("run_safe_command", "Run a shell command with basic safety checks.")
async def run_safe_command(command: str) -> dict[str, Any]:
    blocked = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "shutdown", "reboot"]
    cmd_lower = command.lower().strip()
    for b in blocked:
        if b in cmd_lower:
            return {"success": False, "error": f"Blocked command: {b}"}
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode()[:5000],
            "stderr": stderr.decode()[:2000],
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Command timed out (30s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("get_installed_apps", "List installed macOS applications.")
async def get_installed_apps() -> dict[str, Any]:
    try:
        apps_dir = Path("/Applications")
        apps = sorted([p.stem for p in apps_dir.glob("*.app")])
        return {"success": True, "apps": apps, "count": len(apps)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("get_display_info", "Get display resolution and settings.")
async def get_display_info() -> dict[str, Any]:
    try:
        rc, stdout, stderr = await _run_osascript(
            'tell application "Finder" to get bounds of window of desktop'
        )
        proc = await asyncio.create_subprocess_exec(
            "system_profiler", "SPDisplaysDataType", "-json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        import json
        data = json.loads(out.decode())
        displays = data.get("SPDisplaysDataType", [])
        return {"success": True, "displays": displays}
    except Exception as e:
        return {"success": False, "error": str(e)}
