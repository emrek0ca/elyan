import asyncio
import json
import platform
import re
import time
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Optional, Dict, List
from core.registry import tool
from utils.logger import get_logger
import urllib.parse
import urllib.request

logger = get_logger("system_tools")


def _extract_quoted_text(raw: str) -> str:
    text = str(raw or "")
    m = re.search(r"['\"]([^'\"]{2,280})['\"]", text)
    return str(m.group(1) or "").strip() if m else ""


def _goal_to_computer_steps(goal: str) -> list[dict[str, Any]]:
    low = str(goal or "").strip().lower()
    if not low:
        return []

    steps: list[dict[str, Any]] = []
    browser = "Safari"
    if any(k in low for k in ("chrome", "google chrome")):
        browser = "Google Chrome"

    if any(k in low for k in ("arama", "search", "google", "araştır", "arastir", "resim", "image", "wallpaper")):
        query = str(goal or "").strip()
        # Reduce command noise for search query.
        query = re.sub(r"(?i)\b(safari|chrome|google|aç|ac|open|ara|search|resim|image|duvar kağıdı|wallpaper)\b", " ", query)
        query = " ".join(query.split()).strip() or "genel arama"
        tbm = "isch" if any(k in low for k in ("resim", "image", "fotoğraf", "fotograf", "wallpaper", "duvar kağıdı")) else ""
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        if tbm:
            url += f"&tbm={tbm}"
        steps.extend(
            [
                {"action": "open_app", "params": {"app_name": browser}},
                {"action": "open_url", "params": {"url": url, "browser": browser}},
                {"action": "wait", "params": {"seconds": 1.0}},
            ]
        )

    typed = _extract_quoted_text(goal)
    if typed:
        steps.append({"action": "type_text", "params": {"text": typed, "press_enter": False}})

    if any(k in low for k in ("enter", "gönder", "gonder", "search now")):
        steps.append({"action": "press_key", "params": {"key": "enter"}})

    if any(k in low for k in ("terminal", "komut", "command")):
        steps = [{"action": "open_app", "params": {"app_name": "Terminal"}}, {"action": "wait", "params": {"seconds": 0.6}}] + steps

    # Fallback baseline for generic computer-control intent.
    if not steps:
        steps = [
            {"action": "open_app", "params": {"app_name": browser}},
            {"action": "wait", "params": {"seconds": 0.7}},
        ]
    return steps


def _normalize_text_for_match(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    norm = unicodedata.normalize("NFKD", raw)
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", norm).strip()


def _goal_markers(goal: str) -> list[str]:
    low = _normalize_text_for_match(goal)
    if not low:
        return []
    words = re.findall(r"[a-z0-9]{3,}", low)
    stop = {
        "safari", "google", "open", "ac", "ara", "search", "enter", "bas", "ve", "ile", "icin",
        "gore", "hedef", "gorev", "klavye", "mouse", "bilgisayar", "otomatik", "adim",
    }
    return [w for w in words if w not in stop][:6]


def _screen_matches_goal(goal: str, analysis: Dict[str, Any]) -> bool:
    markers = _goal_markers(goal)
    if not markers:
        return False
    hay = " ".join(
        [
            _normalize_text_for_match(str(analysis.get("summary") or "")),
            _normalize_text_for_match(str(analysis.get("ocr") or "")),
            _normalize_text_for_match(json.dumps(analysis.get("objects", []), ensure_ascii=False)),
        ]
    )
    if not hay.strip():
        return False
    hits = sum(1 for m in markers if m in hay)
    return hits >= max(1, min(2, len(markers)))


def _should_probe_vision(action: str, generated_from_goal: bool) -> bool:
    if generated_from_goal:
        return True
    return action in {"open_url", "type_text", "press_key", "key_combo", "mouse_click"}


def _build_goal_repair_steps(goal: str, analysis: Dict[str, Any]) -> list[dict[str, Any]]:
    _ = analysis
    normalized_goal = _normalize_text_for_match(goal)
    query = " ".join(_goal_markers(goal)) or str(goal or "").strip()
    if not query:
        return []
    steps: list[dict[str, Any]] = [
        {"action": "key_combo", "params": {"combo": "cmd+l"}},
        {"action": "type_text", "params": {"text": query, "press_enter": True}},
        {"action": "wait", "params": {"seconds": 0.9}},
    ]
    if any(k in normalized_goal for k in ("indir", "download", "kaydet", "save")):
        steps.extend(
            [
                {"action": "key_combo", "params": {"combo": "cmd+s"}},
                {"action": "wait", "params": {"seconds": 0.5}},
            ]
        )
    return steps

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


def _escape_applescript_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    return value


def _sanitize_xy(x: int, y: int) -> tuple[int, int]:
    xi = int(x)
    yi = int(y)
    if xi < 0 or yi < 0 or xi > 10000 or yi > 10000:
        raise ValueError("Koordinatlar 0..10000 aralığında olmalı.")
    return xi, yi

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
        process = await asyncio.create_subprocess_exec(
            "open",
            "-a",
            app_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            return {"success": False, "error": error or f"{app_name} açılamadı."}
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

@tool("get_process_info", "Search process details by name. If no name given, list top processes.")
async def get_process_info(process_name: Optional[str] = None, limit: int = 25) -> dict[str, Any]:
    try:
        pname = (process_name or "").strip()
        safe_limit = max(1, min(200, int(limit)))

        if pname:
            cmd = f"ps aux | grep -i '{pname}' | grep -v grep | head -n {safe_limit}"
        else:
            # Top CPU processes when no filter is provided.
            cmd = f"ps aux | head -n 1 && ps aux | sort -nrk 3 | head -n {safe_limit}"

        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        lines = [ln for ln in out.decode(errors="ignore").splitlines() if ln.strip()]
        return {
            "success": True,
            "query": pname or None,
            "count": max(0, len(lines) - (1 if lines else 0)),
            "details": lines,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- MEDIA & INPUT ---

@tool("set_volume", "Change system volume (0-100) or mute/unmute.")
async def set_volume(level: Optional[int] = None, mute: Optional[bool] = None) -> dict[str, Any]:
    try:
        # Support parser payloads such as {"mute": true} without failing.
        if mute is not None:
            # AppleScript syntax:
            # - mute:   set volume with output muted
            # - unmute: set volume without output muted
            script = "set volume with output muted" if bool(mute) else "set volume without output muted"
            code, _, err = await _run_osascript(script)
            if code != 0:
                return {"success": False, "error": err or "Ses durumu değiştirilemedi."}
            out_level = 0 if bool(mute) else (max(0, min(100, int(level))) if level is not None else None)
            if out_level is not None and not bool(mute):
                code2, _, err2 = await _run_osascript(f"set volume output volume {out_level}")
                if code2 != 0:
                    return {"success": False, "error": err2 or "Ses seviyesi ayarlanamadı."}
            return {"success": True, "mute": bool(mute), "level": out_level}

        out_level = 50 if level is None else max(0, min(100, int(level)))
        code, _, err = await _run_osascript(f"set volume output volume {out_level}")
        if code != 0:
            return {"success": False, "error": err or "Ses seviyesi ayarlanamadı."}
        # Ensure unmuted when explicitly setting level.
        code2, _, err2 = await _run_osascript("set volume without output muted")
        if code2 != 0:
            return {"success": False, "error": err2 or "Ses sessiz modu kaldırılamadı."}
        return {"success": True, "level": out_level, "mute": False}
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


@tool("type_text", "Type text into the currently focused app.")
async def type_text(text: str, press_enter: bool = False) -> dict[str, Any]:
    try:
        payload = str(text or "")
        if not payload:
            return {"success": False, "error": "text boş olamaz."}
        esc = _escape_applescript_text(payload)
        script = f'tell application "System Events" to keystroke "{esc}"'
        code, _out, err = await _run_osascript(script)
        if code != 0:
            return {"success": False, "error": err or "Metin yazılamadı."}
        if bool(press_enter):
            code2, _out2, err2 = await _run_osascript('tell application "System Events" to key code 36')
            if code2 != 0:
                return {"success": False, "error": err2 or "Enter tuşuna basılamadı."}
        return {"success": True, "typed_chars": len(payload), "press_enter": bool(press_enter)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("press_key", "Press a key with optional modifiers (cmd, ctrl, alt, shift).")
async def press_key(key: str, modifiers: Optional[List[str]] = None) -> dict[str, Any]:
    try:
        raw_key = str(key or "").strip().lower()
        if not raw_key:
            return {"success": False, "error": "key gerekli."}

        modifier_map = {
            "cmd": "command down",
            "command": "command down",
            "ctrl": "control down",
            "control": "control down",
            "alt": "option down",
            "option": "option down",
            "shift": "shift down",
        }
        mods: list[str] = []
        for m in (modifiers or []):
            mm = str(m or "").strip().lower()
            if mm in modifier_map and modifier_map[mm] not in mods:
                mods.append(modifier_map[mm])
        using_clause = f" using {{{', '.join(mods)}}}" if mods else ""

        keycode_map = {
            "enter": 36,
            "return": 36,
            "tab": 48,
            "space": 49,
            "esc": 53,
            "escape": 53,
            "left": 123,
            "right": 124,
            "down": 125,
            "up": 126,
            "delete": 51,
            "backspace": 51,
        }
        if raw_key in keycode_map:
            script = f'tell application "System Events" to key code {keycode_map[raw_key]}{using_clause}'
        else:
            if len(raw_key) != 1:
                return {"success": False, "error": f"Desteklenmeyen key: {raw_key}"}
            esc_key = _escape_applescript_text(raw_key)
            script = f'tell application "System Events" to keystroke "{esc_key}"{using_clause}'

        code, _out, err = await _run_osascript(script)
        if code != 0:
            return {"success": False, "error": err or "Tuş basımı başarısız."}
        return {"success": True, "key": raw_key, "modifiers": modifiers or []}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("key_combo", "Press a key combo like 'cmd+l' or 'cmd+shift+4'.")
async def key_combo(combo: str) -> dict[str, Any]:
    try:
        parts = [p.strip().lower() for p in str(combo or "").split("+") if p.strip()]
        if len(parts) < 2:
            return {"success": False, "error": "combo formatı geçersiz. Örnek: cmd+l"}
        key = parts[-1]
        modifiers = parts[:-1]
        return await press_key(key=key, modifiers=modifiers)
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("mouse_move", "Move mouse pointer to given screen coordinates.")
async def mouse_move(x: int, y: int) -> dict[str, Any]:
    try:
        xi, yi = _sanitize_xy(x, y)

        try:
            import pyautogui  # type: ignore
            await asyncio.to_thread(pyautogui.moveTo, xi, yi)
            return {"success": True, "x": xi, "y": yi, "method": "pyautogui"}
        except Exception:
            pass

        cliclick = shutil.which("cliclick")
        if cliclick:
            proc = await asyncio.create_subprocess_exec(
                cliclick,
                f"m:{xi},{yi}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {"success": False, "error": stderr.decode("utf-8", errors="ignore").strip() or "Mouse move başarısız."}
            return {"success": True, "x": xi, "y": yi, "method": "cliclick"}

        return {"success": False, "error": "Mouse kontrolü için pyautogui veya cliclick gerekli."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("mouse_click", "Click mouse at given coordinates (left/right/double).")
async def mouse_click(x: int, y: int, button: str = "left", double: bool = False) -> dict[str, Any]:
    try:
        xi, yi = _sanitize_xy(x, y)
        btn = str(button or "left").strip().lower()
        if btn not in {"left", "right"}:
            return {"success": False, "error": "button sadece 'left' veya 'right' olabilir."}

        try:
            import pyautogui  # type: ignore
            clicks = 2 if bool(double) else 1
            await asyncio.to_thread(pyautogui.click, xi, yi, clicks=clicks, button=btn)
            return {"success": True, "x": xi, "y": yi, "button": btn, "double": bool(double), "method": "pyautogui"}
        except Exception:
            pass

        cliclick = shutil.which("cliclick")
        if cliclick:
            if bool(double):
                action = "dc"
            elif btn == "right":
                action = "rc"
            else:
                action = "c"
            proc = await asyncio.create_subprocess_exec(
                cliclick,
                f"{action}:{xi},{yi}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {"success": False, "error": stderr.decode("utf-8", errors="ignore").strip() or "Mouse click başarısız."}
            return {"success": True, "x": xi, "y": yi, "button": btn, "double": bool(double), "method": "cliclick"}

        return {"success": False, "error": "Mouse kontrolü için pyautogui veya cliclick gerekli."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("computer_use", "Execute a deterministic computer-use step list (app/url/keyboard/mouse/wait).")
async def computer_use(
    steps: Optional[List[Dict[str, Any]]] = None,
    goal: str = "",
    auto_plan: bool = True,
    screenshot_after_each: bool = False,
    final_screenshot: bool = True,
    pause_ms: int = 200,
    max_repair_attempts: int = 1,
    vision_feedback: bool = True,
    max_feedback_loops: int = 1,
) -> dict[str, Any]:
    """
    Example step:
    {"action":"open_app","params":{"app_name":"Safari"}}
    {"action":"open_url","params":{"url":"https://google.com","browser":"Safari"}}
    {"action":"key_combo","params":{"combo":"cmd+l"}}
    {"action":"type_text","params":{"text":"köpek resimleri","press_enter":true}}
    {"action":"mouse_click","params":{"x":500,"y":300}}
    {"action":"wait","params":{"seconds":1.2}}
    """
    try:
        raw_steps = steps if isinstance(steps, list) else []
        generated_from_goal = False
        if (not raw_steps) and auto_plan and str(goal or "").strip():
            raw_steps = _goal_to_computer_steps(goal)
            generated_from_goal = True
        if not isinstance(raw_steps, list) or not raw_steps:
            return {"success": False, "error": "steps listesi gerekli. Alternatif: goal alanı ile hedef tanımla."}
        safe_steps = raw_steps[:40]
        pending_steps: list[dict[str, Any]] = list(safe_steps)

        results: list[dict[str, Any]] = []
        screenshots: list[str] = []
        vision_observations: list[dict[str, Any]] = []
        goal_achieved = False
        feedback_budget = max(0, min(3, int(max_feedback_loops or 0)))
        feedback_used = 0

        while pending_steps:
            idx = len(results) + 1
            if idx > 60:
                return {
                    "success": False,
                    "error": "Adım limiti aşıldı (60). Plan kararsız olabilir.",
                    "steps": results,
                    "screenshots": screenshots,
                }
            step = pending_steps.pop(0)
            if not isinstance(step, dict):
                return {"success": False, "error": f"Adım {idx} geçersiz."}
            action = str(step.get("action") or "").strip().lower()
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            if not action:
                return {"success": False, "error": f"Adım {idx} action boş."}

            def _normalize_url(u: str) -> str:
                raw_u = str(u or "").strip()
                if raw_u and not raw_u.startswith(("http://", "https://")):
                    return f"https://{raw_u}"
                return raw_u

            async def _exec_step() -> dict[str, Any]:
                if action == "open_app":
                    return await open_app(app_name=str(params.get("app_name") or "").strip())
                if action == "close_app":
                    return await close_app(app_name=str(params.get("app_name") or "").strip())
                if action == "open_url":
                    return await open_url(url=_normalize_url(str(params.get("url") or "").strip()), browser=params.get("browser"))
                if action == "key_combo":
                    return await key_combo(combo=str(params.get("combo") or "").strip())
                if action == "press_key":
                    mods = params.get("modifiers")
                    if not isinstance(mods, list):
                        mods = []
                    return await press_key(key=str(params.get("key") or "").strip(), modifiers=mods)
                if action == "type_text":
                    text_val = str(params.get("text") or "").strip()
                    if not text_val and str(goal or "").strip():
                        text_val = _extract_quoted_text(goal) or str(goal).strip()
                    return await type_text(
                        text=text_val,
                        press_enter=bool(params.get("press_enter", False)),
                    )
                if action == "mouse_move":
                    return await mouse_move(x=int(params.get("x", 0)), y=int(params.get("y", 0)))
                if action == "mouse_click":
                    return await mouse_click(
                        x=int(params.get("x", 0)),
                        y=int(params.get("y", 0)),
                        button=str(params.get("button") or "left"),
                        double=bool(params.get("double", False)),
                    )
                if action == "wait":
                    try:
                        sec = float(params.get("seconds", 0.5) or 0.5)
                    except Exception:
                        sec = 0.5
                    sec = max(0.0, min(10.0, sec))
                    await asyncio.sleep(sec)
                    return {"success": True, "waited_seconds": sec}
                return {"success": False, "error": f"Adım {idx} desteklenmeyen action: {action}"}

            res = await _exec_step()
            retries_left = max(0, min(2, int(max_repair_attempts or 0)))
            while retries_left > 0 and not bool(res.get("success")):
                retries_left -= 1
                low_err = str(res.get("error") or "").lower()
                if action == "open_url" and "geçersiz" in low_err:
                    params["url"] = _normalize_url(str(params.get("url") or ""))
                elif action in {"mouse_move", "mouse_click"} and any(k in low_err for k in ("pyautogui", "cliclick", "gerekli")):
                    # Soft repair: fall back to keyboard navigation when pointer control unavailable.
                    res = {"success": True, "warning": "mouse_unavailable_fallback", "message": "Mouse kontrol aracı yok; adım atlandı."}
                    break
                else:
                    break
                res = await _exec_step()

            results.append({"step": idx, "action": action, "success": bool(res.get("success")), "result": res})
            if not bool(res.get("success")):
                return {"success": False, "error": f"Adım {idx} başarısız: {res.get('error', 'unknown')}", "steps": results, "screenshots": screenshots}

            if screenshot_after_each:
                shot = await take_screenshot(filename=f"computer_use_step_{idx}_{int(time.time())}.png")
                if shot.get("success") and shot.get("path"):
                    screenshots.append(str(shot.get("path")))

            if vision_feedback and str(goal or "").strip() and _should_probe_vision(action, generated_from_goal):
                analysis = await analyze_screen(prompt=f"Hedef doğrulaması: {goal}")
                brief = {
                    "step": idx,
                    "action": action,
                    "success": bool(analysis.get("success")),
                    "summary": str(analysis.get("summary") or "")[:400],
                    "ocr": str(analysis.get("ocr") or "")[:400],
                }
                vision_observations.append(brief)
                if bool(analysis.get("success")) and _screen_matches_goal(goal, analysis):
                    goal_achieved = True
                    break
                if feedback_used < feedback_budget:
                    repair_steps = _build_goal_repair_steps(goal, analysis)
                    if repair_steps:
                        pending_steps = repair_steps + pending_steps
                        feedback_used += 1

            if pending_steps:
                await asyncio.sleep(max(0.0, min(2.0, pause_ms / 1000.0)))

        final_path = ""
        if final_screenshot:
            shot = await take_screenshot(filename=f"computer_use_final_{int(time.time())}.png")
            if shot.get("success") and shot.get("path"):
                final_path = str(shot.get("path"))
                screenshots.append(final_path)

        # Final visibility check for externally-triggered flows without step-level probes.
        if vision_feedback and str(goal or "").strip() and not goal_achieved and not vision_observations:
            loops = max(0, min(2, int(max_feedback_loops or 0)))
            for _ in range(loops + 1):
                analysis = await analyze_screen(prompt=f"Hedef doğrulaması: {goal}")
                vision_observations.append(
                    {
                        "success": bool(analysis.get("success")),
                        "summary": str(analysis.get("summary") or "")[:400],
                        "ocr": str(analysis.get("ocr") or "")[:400],
                    }
                )
                if bool(analysis.get("success")) and _screen_matches_goal(goal, analysis):
                    goal_achieved = True
                    break
                repair_steps = _build_goal_repair_steps(goal, analysis)
                if not repair_steps:
                    break
                for repair in repair_steps:
                    r_action = str(repair.get("action") or "").strip().lower()
                    r_params = repair.get("params") if isinstance(repair.get("params"), dict) else {}
                    if r_action == "key_combo":
                        await key_combo(combo=str(r_params.get("combo") or "").strip())
                    elif r_action == "type_text":
                        await type_text(
                            text=str(r_params.get("text") or "").strip(),
                            press_enter=bool(r_params.get("press_enter", False)),
                        )
                    elif r_action == "wait":
                        try:
                            sec = float(r_params.get("seconds", 0.5) or 0.5)
                        except Exception:
                            sec = 0.5
                        await asyncio.sleep(max(0.0, min(5.0, sec)))

        return {
            "success": True,
            "steps_executed": len(results),
            "steps": results,
            "screenshots": screenshots,
            "final_screenshot": final_path,
            "generated_from_goal": generated_from_goal,
            "planned_steps": safe_steps if generated_from_goal else [],
            "goal": str(goal or ""),
            "goal_achieved": bool(goal_achieved),
            "vision_observations": vision_observations,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- Desktop & Wallpaper ---

@tool("set_wallpaper", "Masaüstü duvar kağıdını verilen görselle değiştirir.")
async def set_wallpaper(image_path: Optional[str] = None, search_query: Optional[str] = None, image_url: Optional[str] = None) -> dict[str, Any]:
    """
    If image_path is provided, use it.
    If image_url is provided, download it.
    Otherwise download a wallpaper for search_query (default: 'dog wallpaper')
    and set it for all desktops (macOS).
    """
    try:
        target_dir = Path.home() / "Pictures"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / "elyan_wallpaper.jpg"

        async def _download_to_dest(url: str) -> tuple[bool, str]:
            cmd = [
                "curl",
                "-fL",
                "--connect-timeout",
                "10",
                "--max-time",
                "45",
                "-A",
                "Mozilla/5.0 (Elyan)",
                "-o",
                str(dest),
                url,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                return True, ""
            return False, err.decode("utf-8", errors="ignore").strip()

        # Resolve source image
        src_path = None
        if image_path:
            src_path = Path(str(image_path)).expanduser()
            if not src_path.exists():
                return {"success": False, "error": f"Görsel bulunamadı: {src_path}"}
        elif image_url:
            url = image_url.strip()
            if not url.startswith(("http://", "https://")):
                return {"success": False, "error": f"Geçersiz URL: {url}"}
            ok, err = await _download_to_dest(url)
            if not ok:
                return {"success": False, "error": f"Görsel indirilemedi: {err or 'download failed'}"}
            src_path = dest
        else:
            query = search_query or "dog wallpaper"
            candidates = []
            q = urllib.parse.quote_plus(query)
            if any(k in query.lower() for k in ("dog", "köpek", "kopek")):
                candidates.append("https://dog.ceo/api/breeds/image/random")
            candidates.extend(
                [
                    f"https://source.unsplash.com/1920x1080/?{q}",
                    f"https://picsum.photos/seed/{q}/1920/1080",
                ]
            )
            downloaded = False
            last_err = ""
            for candidate in candidates:
                url = candidate
                if "dog.ceo" in candidate:
                    try:
                        with urllib.request.urlopen(candidate, timeout=10) as resp:
                            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                            msg = str(data.get("message") or "").strip()
                            if msg.startswith(("http://", "https://")):
                                url = msg
                    except Exception:
                        pass
                ok, err = await _download_to_dest(url)
                if ok:
                    downloaded = True
                    break
                last_err = err or last_err
            if not downloaded:
                return {"success": False, "error": f"Görsel indirilemedi: {last_err or 'no reachable image source'}"}
            src_path = dest

        # Copy to destination if needed
        if src_path != dest:
            shutil.copyfile(src_path, dest)

        # Set wallpaper on macOS
        script = f'tell application "System Events" to set picture of every desktop to "{dest}"'
        code, _, err = await _run_osascript(script)
        if code != 0:
            return {"success": False, "error": err or "Duvar kağıdı ayarlanamadı."}

        return {
            "success": True,
            "path": str(dest),
            "message": f"Duvar kağıdı güncellendi: {dest}",
            "query": search_query,
        }
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
        proc = await asyncio.create_subprocess_exec(
            "screencapture",
            "-x",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            error = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            return {"success": False, "error": error or "Ekran görüntüsü alınamadı."}
        if not path.exists():
            return {"success": False, "error": f"Ekran görüntüsü dosyası oluşmadı: {path}"}
        size_bytes = int(path.stat().st_size) if path.is_file() else 0
        if size_bytes <= 0:
            return {"success": False, "error": f"Ekran görüntüsü boş görünüyor: {path}"}
        return {"success": True, "path": str(path), "size_bytes": size_bytes}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("analyze_screen", "Capture current screen and analyze its content with vision AI.")
async def analyze_screen(prompt: str = "Ekranda ne var? Özetle.") -> dict[str, Any]:
    """
    1) Ekran görüntüsü alır (Desktop'a kaydeder)
    2) Vision modeli ile analiz eder (Gemini varsa onu, yoksa yerel Ollama/Llava)
    3) Yapılandırılmış çıktı döner: ocr, objects, summary, risks
    """
    try:
        shot_name = f"screen_{int(time.time())}.png"
        screenshot = await take_screenshot(shot_name)
        if not screenshot.get("success"):
            return {"success": False, "error": screenshot.get("error", "Ekran görüntüsü alınamadı.")}
        shot_path = screenshot.get("path")
        from tools.vision_tools import analyze_image
        analysis = await analyze_image(shot_path, prompt=prompt)
        summary = analysis.get("analysis", "")
        # Basit ayrıştırma: OCR/objects alanları için placeholders
        result = {
            "success": bool(analysis.get("success")),
            "path": shot_path,
            "summary": summary,
            "ocr": analysis.get("ocr", ""),
            "objects": analysis.get("objects", []),
            "risks": analysis.get("risks", []),
            "provider": analysis.get("provider", ""),
            "error": analysis.get("error", ""),
        }
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("capture_region", "Capture a selected screen region (macOS screencapture -R).")
async def capture_region(x: int, y: int, width: int, height: int, filename: Optional[str] = None) -> dict[str, Any]:
    """
    Ekranın belirli bir bölgesini yakalar. Parametreler piksel cinsindendir.
    """
    try:
        shot_name = filename or f"region_{int(time.time())}.png"
        path = Path.home() / "Desktop" / shot_name
        region_arg = f"{int(x)},{int(y)},{int(width)},{int(height)}"
        proc = await asyncio.create_subprocess_exec(
            "screencapture",
            "-x",
            "-R",
            region_arg,
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            error = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            return {"success": False, "error": error or "Bölge yakalama başarısız."}
        if not path.exists():
            return {"success": False, "error": f"Bölge görüntüsü dosyası oluşmadı: {path}"}
        size_bytes = int(path.stat().st_size) if path.is_file() else 0
        if size_bytes <= 0:
            return {"success": False, "error": f"Bölge görüntüsü boş görünüyor: {path}"}
        return {"success": True, "path": str(path), "size_bytes": size_bytes}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("send_notification", "Display a system notification.")
async def send_notification(title: str = "Elyan", message: str = "") -> dict[str, Any]:
    try:
        if not message:
            message = title or "Bildirim"
        script = f'display notification "{message}" with title "{title}"'
        await _run_osascript(script)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool("open_url", "Open a website in default browser or a specific browser app.")
async def open_url(url: str, browser: Optional[str] = None) -> dict[str, Any]:
    try:
        target_url = str(url or "").strip()
        if not target_url:
            return {"success": False, "error": "url gerekli."}
        if not target_url.startswith("http"):
            target_url = "https://" + target_url

        app_name = str(browser or "").strip()
        if app_name:
            if platform.system() == "Darwin":
                # Open in specific browser app (e.g. Safari) instead of default browser.
                script = (
                    f'tell application "{app_name}"\n'
                    "activate\n"
                    f'open location "{target_url}"\n'
                    "end tell"
                )
                code, _out, err = await _run_osascript(script)
                if code != 0:
                    return {"success": False, "error": err or f"{app_name} içinde URL açılamadı."}
                return {"success": True, "url": target_url, "browser": app_name}

            proc = await asyncio.create_subprocess_exec(
                "open",
                "-a",
                app_name,
                target_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {"success": False, "error": stderr.decode("utf-8", errors="ignore").strip() or f"{app_name} açılamadı."}
            return {"success": True, "url": target_url, "browser": app_name}

        await asyncio.create_subprocess_exec("open", target_url)
        return {"success": True, "url": target_url}
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


def _normalize_ide_name(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text in {"", "default"}:
        return "vscode"

    aliases = {
        "vscode": "vscode",
        "vs code": "vscode",
        "visual studio code": "vscode",
        "code": "vscode",
        "cursor": "cursor",
        "windsurf": "windsurf",
        "codeium windsurf": "windsurf",
        "antigravity": "antigravity",
        "gravity": "antigravity",
        "ag": "antigravity",
    }
    return aliases.get(text, text)


@tool("open_project_in_ide", "Open a project folder in IDE (VS Code/Cursor/Windsurf/Antigravity).")
async def open_project_in_ide(project_path: str, ide: str = "vscode") -> dict[str, Any]:
    try:
        normalized_ide = _normalize_ide_name(ide)
        target = Path(str(project_path or "")).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Project path bulunamadı: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Project path klasör olmalı: {target}"}

        ide_map = {
            "vscode": {
                "app_candidates": ["Visual Studio Code", "Code"],
                "cli_candidates": ["code"],
            },
            "cursor": {
                "app_candidates": ["Cursor"],
                "cli_candidates": ["cursor"],
            },
            "windsurf": {
                "app_candidates": ["Windsurf", "Codeium Windsurf"],
                "cli_candidates": ["windsurf"],
            },
            "antigravity": {
                "app_candidates": ["Antigravity", "Antigravity IDE", "AntiGravity"],
                "cli_candidates": ["antigravity", "gravity"],
            },
        }
        config = ide_map.get(normalized_ide) or ide_map["vscode"]

        # Prefer native CLI when installed (faster and opens folder directly).
        for cli_name in config.get("cli_candidates", []):
            cli_bin = shutil.which(cli_name)
            if not cli_bin:
                continue
            proc = await asyncio.create_subprocess_exec(
                cli_bin,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {
                    "success": True,
                    "ide": normalized_ide,
                    "project_path": str(target),
                    "method": "cli",
                    "command": f"{cli_name} {target}",
                    "message": f"Proje IDE'de açıldı ({normalized_ide}).",
                }
            err = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            logger.warning(f"IDE CLI open failed ({cli_name}): {err}")

        # Fallback: macOS open -a "<app>" "<path>"
        errors: list[str] = []
        for app_name in config.get("app_candidates", []):
            proc = await asyncio.create_subprocess_exec(
                "open",
                "-a",
                app_name,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {
                    "success": True,
                    "ide": normalized_ide,
                    "project_path": str(target),
                    "method": "open-app",
                    "app": app_name,
                    "message": f"Proje {app_name} ile açıldı.",
                }
            err = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
            if err:
                errors.append(f"{app_name}: {err}")

        details = " | ".join(errors[:3]) if errors else "uygulama bulunamadı veya açılamadı"
        # Graceful fallback: open folder in Finder so workflow can continue.
        proc = await asyncio.create_subprocess_exec(
            "open",
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return {
                "success": True,
                "warning": f"IDE açılamadı ({normalized_ide}): {details}",
                "ide": normalized_ide,
                "project_path": str(target),
                "method": "finder-fallback",
                "message": f"IDE bulunamadı, proje klasörü Finder'da açıldı: {target}",
            }
        fallback_err = (stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")).strip()
        return {
            "success": False,
            "error": f"IDE açılamadı ({normalized_ide}): {details} | Finder fallback başarısız: {fallback_err or 'open failed'}",
            "ide": normalized_ide,
            "project_path": str(target),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("get_weather", "Get current weather and forecast for a city using web search.")
async def get_weather(city: str = "") -> dict[str, Any]:
    """Hava durumu bilgisi — wttr.in servisi üzerinden JSON."""
    try:
        import httpx
        location = (city or "Istanbul").strip()
        # wttr.in provides free weather data in JSON format
        url = f"https://wttr.in/{location}?format=j1"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Elyan-Bot/1.0"})
            if resp.status_code != 200:
                raise ValueError(f"wttr.in returned {resp.status_code}")
            data = resp.json()

        current = data.get("current_condition", [{}])[0]
        temp_c = current.get("temp_C", "?")
        feels_like = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc = (current.get("weatherDesc", [{}])[0] or {}).get("value", "Bilinmiyor")
        wind_kmph = current.get("windspeedKmph", "?")

        # Nearest area
        nearest = data.get("nearest_area", [{}])[0]
        area_name = (nearest.get("areaName", [{}])[0] or {}).get("value", location)
        country = (nearest.get("country", [{}])[0] or {}).get("value", "")

        # Forecast (next 2 days)
        forecasts = []
        for day in data.get("weather", [])[:3]:
            date = day.get("date", "")
            max_c = day.get("maxtempC", "?")
            min_c = day.get("mintempC", "?")
            desc_day = (day.get("hourly", [{}])[4] or {})
            desc_day_txt = (desc_day.get("weatherDesc", [{}])[0] or {}).get("value", "")
            forecasts.append({"date": date, "max_c": max_c, "min_c": min_c, "desc": desc_day_txt})

        location_str = f"{area_name}, {country}" if country else area_name
        summary = (
            f"🌤 **{location_str}** hava durumu:\n"
            f"Sıcaklık: {temp_c}°C (hissedilen {feels_like}°C)\n"
            f"Durum: {desc}\n"
            f"Nem: %{humidity} | Rüzgar: {wind_kmph} km/s"
        )

        return {
            "success": True,
            "location": location_str,
            "current": {
                "temp_c": temp_c,
                "feels_like_c": feels_like,
                "humidity_pct": humidity,
                "description": desc,
                "wind_kmph": wind_kmph,
            },
            "forecast": forecasts,
            "summary": summary,
        }
    except Exception as e:
        logger.warning(f"Weather lookup failed: {e}")
        # Fallback: basic macOS weather via Siri/weather URL
        try:
            city_enc = (city or "Istanbul").replace(" ", "+")
            proc = await asyncio.create_subprocess_shell(
                f"curl -s 'https://wttr.in/{city_enc}?format=3'",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            text = out.decode("utf-8", errors="ignore").strip()
            if text:
                return {"success": True, "location": city or "Istanbul",
                        "summary": f"🌤 {text}", "current": {}, "forecast": []}
        except Exception:
            pass
        return {"success": False, "error": f"Hava durumu alınamadı: {e}. İnternet bağlantısını kontrol et."}


@tool("run_code", "Write and execute Python code, show output.")
async def run_code(code: str = "", language: str = "python", description: str = "") -> dict[str, Any]:
    """Python kodu yaz ve çalıştır — çıktıyı döndür."""
    import tempfile
    try:
        if not code or not code.strip():
            return {"success": False, "error": "Çalıştırılacak kod boş. Lütfen kod girin."}

        lang = (language or "python").lower()
        if lang not in ("python", "python3", "py"):
            return {"success": False, "error": f"Desteklenmeyen dil: {language}. Şu an sadece Python destekleniyor."}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        proc = await asyncio.create_subprocess_exec(
            "python3", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": "Kod 30 saniye içinde tamamlanamadı (timeout)."}
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        stdout_text = stdout_b.decode("utf-8", errors="ignore").strip()
        stderr_text = stderr_b.decode("utf-8", errors="ignore").strip()
        ok = proc.returncode == 0

        return {
            "success": ok,
            "code": code,
            "language": "python",
            "output": stdout_text,
            "error_output": stderr_text,
            "return_code": proc.returncode,
            "summary": (
                f"✅ Kod çalıştı.\n```\n{stdout_text[:2000]}\n```" if ok
                else f"❌ Hata:\n```\n{stderr_text[:1000]}\n```"
            ),
        }
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
