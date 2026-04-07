"""
core/computer/app_controller.py
───────────────────────────────────────────────────────────────────────────────
AppController — high-level macOS system interactions.
"""
from __future__ import annotations
import asyncio, re
from utils.logger import get_logger

logger = get_logger("app_controller")
_TIMEOUT = 5.0


async def _run(cmd: list[str], input_bytes: bytes | None = None) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_bytes else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(input_bytes), timeout=_TIMEOUT)
        return proc.returncode == 0, out.decode().strip()
    except Exception as exc:
        logger.debug(f"_run {cmd[0]}: {exc}")
        return False, ""


async def _osascript(script: str) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        return proc.returncode == 0, out.decode().strip()
    except Exception as exc:
        logger.debug(f"osascript: {exc}")
        return False, ""


class AppController:

    async def open_url(self, url: str, browser: str = "Safari") -> bool:
        ok, _ = await _osascript(f'tell application "{browser}" to open location "{url}"\ntell application "{browser}" to activate')
        return ok

    async def open_file(self, path: str) -> bool:
        ok, _ = await _run(["open", path])
        return ok

    async def show_notification(self, title: str, message: str, sound: bool = True) -> bool:
        sound_clause = ' sound name "Glass"' if sound else ""
        ok, _ = await _osascript(
            f'display notification "{message}" with title "{title}"{sound_clause}'
        )
        return ok

    async def get_clipboard(self) -> str:
        _, out = await _run(["pbpaste"])
        return out

    async def set_clipboard(self, text: str) -> bool:
        ok, _ = await _run(["pbcopy"], text.encode())
        return ok

    async def get_volume(self) -> int:
        _, out = await _osascript("output volume of (get volume settings)")
        try:
            return int(out)
        except Exception:
            return 50

    async def set_volume(self, level: int) -> bool:
        level = max(0, min(100, level))
        ok, _ = await _osascript(f"set volume output volume {level}")
        return ok

    async def get_battery_info(self) -> dict:
        result = {"percent": 100, "charging": True, "time_remaining": ""}
        try:
            _, out = await _run(["pmset", "-g", "batt"])
            m = re.search(r"(\d+)%", out)
            if m:
                result["percent"] = int(m.group(1))
            # "AC Power" = charging; "Battery Power" + no "charging" keyword = discharging
            result["charging"] = "AC Power" in out or (
                "charging" in out.lower() and "discharging" not in out.lower()
            )
            tm = re.search(r"(\d+:\d+) remaining", out)
            if tm:
                result["time_remaining"] = tm.group(1)
        except Exception:
            pass
        return result

    async def get_cpu_usage(self) -> float:
        _, out = await _run(["top", "-l", "1", "-n", "0"])
        try:
            m = re.search(r"CPU usage:\s+([\d.]+)%\s+user,\s+([\d.]+)%\s+sys", out)
            if m:
                return round(float(m.group(1)) + float(m.group(2)), 1)
        except Exception:
            pass
        return 0.0

    async def get_disk_usage(self) -> dict:
        _, out = await _run(["df", "-k", "/"])
        result = {"free_gb": 0.0, "total_gb": 0.0, "used_pct": 0.0}
        try:
            lines = out.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                total_kb = int(parts[1])
                used_kb = int(parts[2])
                free_kb = int(parts[3])
                result["total_gb"] = round(total_kb / 1_048_576, 1)
                result["free_gb"] = round(free_kb / 1_048_576, 1)
                result["used_pct"] = round(used_kb / total_kb * 100, 1) if total_kb else 0.0
        except Exception:
            pass
        return result


_instance: AppController | None = None

def get_app_controller() -> AppController:
    global _instance
    if _instance is None:
        _instance = AppController()
    return _instance

__all__ = ["AppController", "get_app_controller"]
