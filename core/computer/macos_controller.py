"""
core/computer/macos_controller.py
───────────────────────────────────────────────────────────────────────────────
MacOSController — AppleScript + subprocess-based macOS automation.
"""
from __future__ import annotations
import asyncio, tempfile
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("macos_controller")
_TIMEOUT = 5.0


async def _osascript(script: str) -> tuple[bool, str]:
    """Run AppleScript, return (success, stdout)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        return proc.returncode == 0, out.decode().strip()
    except Exception as exc:
        logger.debug(f"osascript error: {exc}")
        return False, ""


async def _run(cmd: list[str], input_data: bytes | None = None) -> tuple[bool, str]:
    """Run subprocess command."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(input_data), timeout=_TIMEOUT)
        return proc.returncode == 0, out.decode().strip()
    except Exception as exc:
        logger.debug(f"subprocess error {cmd}: {exc}")
        return False, ""


class MacOSController:

    # ── Mouse ────────────────────────────────────────────────────────────────

    async def click(self, x: int, y: int) -> bool:
        ok, _ = await _run(["cliclick", f"c:{x},{y}"])
        if ok:
            return True
        # Fallback: AppleScript
        ok, _ = await _osascript(
            f'tell application "System Events" to click at {{{x}, {y}}}'
        )
        return ok

    async def scroll(self, direction: str = "down", amount: int = 3, x: int = 500, y: int = 500) -> bool:
        sign = "-" if direction == "down" else ""
        ok, _ = await _run(["cliclick", f"kd:scroll", f"ku:scroll"])
        if not ok:
            script = (
                f'tell application "System Events" to scroll '
                f'{"down" if direction == "down" else "up"} by {amount}'
            )
            ok, _ = await _osascript(script)
        return ok

    # ── Keyboard ─────────────────────────────────────────────────────────────

    async def type_text(self, text: str, target_app: str = "") -> bool:
        safe = text.replace('"', '\\"')
        if target_app:
            script = f'tell application "{target_app}" to activate\ndelay 0.2\ntell application "System Events" to keystroke "{safe}"'
        else:
            script = f'tell application "System Events" to keystroke "{safe}"'
        ok, _ = await _osascript(script)
        return ok

    async def run_shortcut(self, keys: str) -> bool:
        """keys like 'cmd+c', 'cmd+tab', 'escape'"""
        _modifier_map = {
            "cmd": "command down", "command": "command down",
            "opt": "option down", "option": "option down",
            "ctrl": "control down", "control": "control down",
            "shift": "shift down",
        }
        parts = [p.strip().lower() for p in keys.split("+")]
        key = parts[-1]
        modifiers = [_modifier_map[p] for p in parts[:-1] if p in _modifier_map]
        using = "{" + ", ".join(modifiers) + "}" if modifiers else ""
        mod_clause = f" using {using}" if using else ""
        script = f'tell application "System Events" to keystroke "{key}"{mod_clause}'
        ok, _ = await _osascript(script)
        return ok

    # ── Applications ─────────────────────────────────────────────────────────

    async def open_app(self, app_name: str) -> bool:
        ok, _ = await _osascript(f'tell application "{app_name}" to activate')
        return ok

    async def quit_app(self, app_name: str) -> bool:
        ok, _ = await _osascript(f'tell application "{app_name}" to quit')
        return ok

    async def get_frontmost_app(self) -> str:
        _, out = await _osascript(
            'tell application "System Events" to get name of first application process whose frontmost is true'
        )
        return out

    async def list_open_apps(self) -> list[str]:
        _, out = await _osascript(
            'tell application "System Events" to get name of every application process whose background only is false'
        )
        if not out:
            return []
        return [a.strip() for a in out.split(",") if a.strip()]

    # ── Screenshot ───────────────────────────────────────────────────────────

    async def take_screenshot(self, region: tuple | None = None) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        cmd = ["screencapture", "-x", "-t", "png"]
        if region:
            x, y, w, h = region
            cmd += ["-R", f"{x},{y},{w},{h}"]
        cmd.append(path)
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=_TIMEOUT)
            return Path(path).read_bytes()
        except Exception as exc:
            logger.debug(f"screenshot failed: {exc}")
            return b""
        finally:
            Path(path).unlink(missing_ok=True)


_instance: MacOSController | None = None

def get_macos_controller() -> MacOSController:
    global _instance
    if _instance is None:
        _instance = MacOSController()
    return _instance

__all__ = ["MacOSController", "get_macos_controller"]
