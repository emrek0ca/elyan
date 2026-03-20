from __future__ import annotations

import asyncio
import ctypes
import csv
import importlib.util
import io
import json
import os
import platform
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.confidence import coerce_confidence
from core.dependencies import get_system_dependency_runtime
from tools.vision_tools import analyze_image


AsyncDictCallable = Callable[..., Awaitable[dict[str, Any]]]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _ensure_system_binary(binary: str, *, allow_install: bool = True) -> bool:
    try:
        record = get_system_dependency_runtime().ensure_binary(
            binary,
            allow_install=allow_install,
            skill_name="screen_operator",
            tool_name=binary,
        )
        return str(record.status).lower() in {"ready", "installed"}
    except Exception:
        return False


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    return coerce_confidence(value, default)


def _normalize_role(role: Any) -> str:
    raw = str(role or "").strip().lower()
    if not raw:
        return "unknown"
    replacements = {
        "push button": "button",
        "button": "button",
        "text": "text",
        "text field": "text_field",
        "editable text": "text_field",
        "entry": "text_field",
        "link": "link",
        "menu item": "menu_item",
        "menuitem": "menu_item",
        "tab": "tab",
        "checkbox": "checkbox",
        "radio button": "radio",
        "combo box": "combo_box",
        "list item": "list_item",
        "window": "window",
        "pane": "group",
        "group": "group",
    }
    for needle, replacement in replacements.items():
        if needle in raw:
            return replacement
    return raw.replace(" ", "_")


def _fallback_accessibility_snapshot_from_metadata(
    *,
    frontmost_app: str,
    window_title: str,
    bounds: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    if frontmost_app:
        elements.append({"label": frontmost_app, "role": "frontmost_app", "source": "window_metadata", "confidence": 0.92})
    if window_title and window_title != frontmost_app:
        row: dict[str, Any] = {"label": window_title, "role": "window_title", "source": "window_metadata", "confidence": 0.9}
        if isinstance(bounds, dict):
            row.update({k: int(v) for k, v in bounds.items() if isinstance(v, (int, float))})
        elements.append(row)
    return {
        "success": True,
        "frontmost_app": frontmost_app,
        "window_title": window_title,
        "elements": elements,
        "summary": window_title or frontmost_app or "",
        "source": "fallback/native_window_metadata",
        "warning": reason,
    }


def _window_title_from_ctypes() -> dict[str, Any]:
    user32 = getattr(ctypes, "windll", None)
    if user32 is None:
        return {"success": False, "error": "ctypes_windll_unavailable"}
    user32 = getattr(user32, "user32", None)
    if user32 is None:
        return {"success": False, "error": "user32_unavailable"}
    hwnd = int(getattr(user32, "GetForegroundWindow", lambda: 0)() or 0)
    if not hwnd:
        return {"success": False, "error": "foreground_window_unavailable"}
    length = int(getattr(user32, "GetWindowTextLengthW", lambda _hwnd: 0)(hwnd) or 0)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    getattr(user32, "GetWindowTextW", lambda *_args: 0)(hwnd, buffer, len(buffer))
    title = str(buffer.value or "").strip()
    rect = getattr(ctypes, "wintypes", None)
    bounds: dict[str, Any] = {}
    if rect is not None and hasattr(rect, "RECT"):
        try:
            box = rect.RECT()
            if getattr(user32, "GetWindowRect", lambda *_args: 0)(hwnd, ctypes.byref(box)):
                bounds = {
                    "x": int(box.left),
                    "y": int(box.top),
                    "width": int(box.right - box.left),
                    "height": int(box.bottom - box.top),
                }
        except Exception:
            bounds = {}
    return {
        "success": True,
        "frontmost_app": title or "Windows",
        "window_title": title,
        "bounds": bounds,
    }


async def _linux_window_title() -> dict[str, Any]:
    if not shutil.which("xdotool"):
        _ensure_system_binary("xdotool")
    if shutil.which("xdotool"):
        proc = await asyncio.create_subprocess_exec(
            "xdotool",
            "getactivewindow",
            "getwindowname",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            title = str(stdout.decode("utf-8", errors="ignore").strip())
            if title:
                return {"success": True, "frontmost_app": title, "window_title": title, "bounds": {}}
        err = stderr.decode("utf-8", errors="ignore").strip()
        if err:
            return {"success": False, "error": err}
    if not shutil.which("wmctrl"):
        _ensure_system_binary("wmctrl")
    if not shutil.which("xprop"):
        _ensure_system_binary("xprop")
    if shutil.which("wmctrl") and shutil.which("xprop"):
        try:
            active_proc = await asyncio.create_subprocess_exec(
                "xprop",
                "-root",
                "_NET_ACTIVE_WINDOW",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            active_out, _ = await active_proc.communicate()
            match = re.search(r"0x[0-9a-fA-F]+", active_out.decode("utf-8", errors="ignore"))
            if match:
                win_id = match.group(0)
                name_proc = await asyncio.create_subprocess_exec(
                    "xprop",
                    "-id",
                    win_id,
                    "WM_NAME",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                name_out, _ = await name_proc.communicate()
                title_match = re.search(r'=\s*"([^"]+)"', name_out.decode("utf-8", errors="ignore"))
                title = str(title_match.group(1) if title_match else "").strip()
                if title:
                    return {"success": True, "frontmost_app": title, "window_title": title, "bounds": {}}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    return {"success": False, "error": "window_metadata_unsupported"}


def _collect_uia_elements(control: Any, *, max_depth: int = 2, max_items: int = 24) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []

    def _walk(node: Any, depth: int) -> None:
        if node is None or depth > max_depth or len(elements) >= max_items:
            return
        label = str(getattr(node, "Name", None) or getattr(node, "name", None) or "").strip()
        role = _normalize_role(getattr(node, "ControlTypeName", None) or getattr(node, "control_type", None) or getattr(node, "RoleName", None) or getattr(node, "role_name", None) or "")
        if hasattr(node, "BoundingRectangle"):
            try:
                rect = getattr(node, "BoundingRectangle")
                if rect:
                    x = int(getattr(rect, "left", getattr(rect, "x", 0)) or 0)
                    y = int(getattr(rect, "top", getattr(rect, "y", 0)) or 0)
                    width = int((getattr(rect, "right", 0) or 0) - (getattr(rect, "left", 0) or 0))
                    height = int((getattr(rect, "bottom", 0) or 0) - (getattr(rect, "top", 0) or 0))
                else:
                    x = y = width = height = 0
            except Exception:
                x = y = width = height = 0
        else:
            x = y = width = height = 0
        if label or role:
            row = {
                "label": label,
                "role": role,
                "source": "uiautomation",
                "confidence": 0.8 if label else 0.55,
            }
            if any(v for v in (x, y, width, height)):
                row.update({"x": x, "y": y, "width": width, "height": height})
            elements.append(row)
        try:
            children = list(getattr(node, "GetChildren", lambda: [])() or [])
        except Exception:
            children = []
        for child in children:
            _walk(child, depth + 1)

    _walk(control, 0)
    return elements


def _collect_pyatspi_elements(node: Any, *, max_depth: int = 2, max_items: int = 24) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []

    def _role_name(item: Any) -> str:
        role = ""
        try:
            getter = getattr(item, "getRoleName", None)
            if callable(getter):
                role = str(getter() or "").strip()
        except Exception:
            role = ""
        if not role:
            role = str(getattr(item, "roleName", "") or getattr(item, "role_name", "") or "").strip()
        return _normalize_role(role)

    def _walk(item: Any, depth: int) -> None:
        if item is None or depth > max_depth or len(elements) >= max_items:
            return
        label = str(getattr(item, "name", None) or getattr(item, "label", None) or "").strip()
        role = _role_name(item)
        if label or role:
            elements.append({
                "label": label,
                "role": role,
                "source": "pyatspi",
                "confidence": 0.82 if label else 0.5,
            })
        try:
            child_count = int(getattr(item, "childCount", 0) or 0)
        except Exception:
            child_count = 0
        for idx in range(min(child_count, max_items - len(elements))):
            try:
                child = item.getChildAtIndex(idx)
            except Exception:
                child = None
            _walk(child, depth + 1)

    _walk(node, 0)
    return elements

@dataclass(frozen=True)
class ScreenOperatorServices:
    take_screenshot: AsyncDictCallable
    capture_region: AsyncDictCallable
    get_window_metadata: Callable[[], Awaitable[dict[str, Any]]]
    get_accessibility_snapshot: Callable[[], Awaitable[dict[str, Any]]]
    run_ocr: Callable[[str], Awaitable[dict[str, Any]]]
    run_vision: Callable[[str, str], Awaitable[dict[str, Any]]]
    mouse_move: AsyncDictCallable
    mouse_click: AsyncDictCallable
    type_text: AsyncDictCallable
    press_key: AsyncDictCallable
    key_combo: AsyncDictCallable
    sleep: Callable[[float], Awaitable[None]]


async def _run_osascript(script: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        int(process.returncode or 0),
        stdout.decode("utf-8", errors="ignore").strip(),
        stderr.decode("utf-8", errors="ignore").strip(),
    )


async def _default_window_metadata() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        try:
            data = await asyncio.to_thread(_window_title_from_ctypes)
            if bool(data.get("success")):
                return data
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    elif system not in {"Darwin", "Windows"}:
        data = await _linux_window_title()
        if bool(data.get("success")):
            return data
        # fall through to mac-style unsupported message only after trying Linux helpers
        linux_error = str(data.get("error") or "").strip()
        if linux_error and linux_error != "window_metadata_unsupported":
            return {"success": False, "error": linux_error}
        return {"success": False, "error": "window_metadata_unsupported"}
    if system != "Darwin":
        # On non-Darwin systems, we already attempted the native helpers above.
        return {"success": False, "error": "window_metadata_unsupported"}
    script = r'''
        tell application "System Events"
            set appName to ""
            set windowName to ""
            set posX to ""
            set posY to ""
            set winW to ""
            set winH to ""
            try
                set frontProc to first application process whose frontmost is true
                set appName to name of frontProc as text
                try
                    set frontWin to front window of frontProc
                    set windowName to name of frontWin as text
                    set winPos to position of frontWin
                    set winSize to size of frontWin
                    set posX to item 1 of winPos as text
                    set posY to item 2 of winPos as text
                    set winW to item 1 of winSize as text
                    set winH to item 2 of winSize as text
                end try
            end try
            return appName & "||" & windowName & "||" & posX & "||" & posY & "||" & winW & "||" & winH
        end tell
    '''
    code, out, err = await _run_osascript(script)
    if code != 0:
        return {"success": False, "error": err or "window_metadata_failed"}
    parts = str(out or "").split("||")
    frontmost_app = str(parts[0] if len(parts) > 0 else "").strip()
    window_title = str(parts[1] if len(parts) > 1 else "").strip()
    bounds = {}
    try:
        if len(parts) >= 6 and all(str(parts[idx]).strip() for idx in range(2, 6)):
            bounds = {
                "x": int(parts[2]),
                "y": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
            }
    except Exception:
        bounds = {}
    return {
        "success": True,
        "frontmost_app": frontmost_app,
        "window_title": window_title,
        "bounds": bounds,
    }


async def _default_accessibility_snapshot() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        try:
            if _module_available("uiautomation"):
                import uiautomation as auto  # type: ignore

                focused = None
                for getter_name in ("GetFocusedControl", "GetForegroundControl", "GetRootControl"):
                    getter = getattr(auto, getter_name, None)
                    if callable(getter):
                        try:
                            focused = getter()
                        except Exception:
                            focused = None
                        if focused is not None:
                            break
                elements = _collect_uia_elements(focused, max_depth=2, max_items=24) if focused is not None else []
                window_meta = await _default_window_metadata()
                if not elements:
                    return _fallback_accessibility_snapshot_from_metadata(
                        frontmost_app=str(window_meta.get("frontmost_app") or "").strip(),
                        window_title=str(window_meta.get("window_title") or "").strip(),
                        bounds=dict(window_meta.get("bounds") or {}) if isinstance(window_meta.get("bounds"), dict) else {},
                        reason="uiautomation_empty",
                    )
                return {
                    "success": True,
                    "frontmost_app": str(window_meta.get("frontmost_app") or "").strip(),
                    "window_title": str(window_meta.get("window_title") or "").strip(),
                    "elements": elements,
                    "source": "uiautomation",
                }
        except Exception as exc:
            return {"success": False, "error": str(exc), "elements": []}
        window_meta = await _default_window_metadata()
        return _fallback_accessibility_snapshot_from_metadata(
            frontmost_app=str(window_meta.get("frontmost_app") or "").strip(),
            window_title=str(window_meta.get("window_title") or "").strip(),
            bounds=dict(window_meta.get("bounds") or {}) if isinstance(window_meta.get("bounds"), dict) else {},
            reason="uiautomation_unavailable",
        )
    if system not in {"Darwin", "Windows"}:
        try:
            if _module_available("pyatspi"):
                import pyatspi  # type: ignore

                desktop = None
                registry = getattr(pyatspi, "Registry", None)
                getter = getattr(registry, "getDesktop", None) if registry is not None else None
                if callable(getter):
                    try:
                        desktop = getter(0)
                    except Exception:
                        desktop = None
                if desktop is not None:
                    elements = _collect_pyatspi_elements(desktop, max_depth=2, max_items=24)
                    window_meta = await _default_window_metadata()
                    if not elements:
                        return _fallback_accessibility_snapshot_from_metadata(
                            frontmost_app=str(window_meta.get("frontmost_app") or "").strip(),
                            window_title=str(window_meta.get("window_title") or "").strip(),
                            bounds=dict(window_meta.get("bounds") or {}) if isinstance(window_meta.get("bounds"), dict) else {},
                            reason="pyatspi_empty",
                        )
                    return {
                        "success": True,
                        "frontmost_app": str(window_meta.get("frontmost_app") or "").strip(),
                        "window_title": str(window_meta.get("window_title") or "").strip(),
                        "elements": elements,
                        "source": "pyatspi",
                    }
        except Exception as exc:
            return {"success": False, "error": str(exc), "elements": []}
        window_meta = await _default_window_metadata()
        return _fallback_accessibility_snapshot_from_metadata(
            frontmost_app=str(window_meta.get("frontmost_app") or "").strip(),
            window_title=str(window_meta.get("window_title") or "").strip(),
            bounds=dict(window_meta.get("bounds") or {}) if isinstance(window_meta.get("bounds"), dict) else {},
            reason="pyatspi_unavailable",
        )
    script = r'''
        set AppleScript's text item delimiters to linefeed
        tell application "System Events"
            set linesOut to {}
            try
                set frontProc to first application process whose frontmost is true
                set appName to name of frontProc as text
                set winName to ""
                try
                    set winName to name of front window of frontProc as text
                end try
                set end of linesOut to "WINDOW||" & appName & "||" & winName
                tell front window of frontProc
                    my collectElements(buttons, "button", linesOut, 18)
                    my collectElements(text fields, "text_field", linesOut, 12)
                    my collectElements(static texts, "static_text", linesOut, 24)
                    my collectElements(groups, "group", linesOut, 8)
                end tell
            end try
            return linesOut as text
        end tell

        on collectElements(theItems, roleName, linesOut, maxCount)
            try
                set itemCount to count of theItems
                if itemCount > maxCount then
                    set itemCount to maxCount
                end if
                repeat with idx from 1 to itemCount
                    try
                        set el to item idx of theItems
                        set elName to ""
                        set posX to ""
                        set posY to ""
                        set sizeW to ""
                        set sizeH to ""
                        set enabledVal to "true"
                        try
                            set elName to name of el as text
                        end try
                        try
                            set elPos to position of el
                            set posX to item 1 of elPos as text
                            set posY to item 2 of elPos as text
                        end try
                        try
                            set elSize to size of el
                            set sizeW to item 1 of elSize as text
                            set sizeH to item 2 of elSize as text
                        end try
                        try
                            set enabledVal to (enabled of el) as text
                        end try
                        set end of linesOut to "ELEMENT||" & roleName & "||" & elName & "||" & posX & "||" & posY & "||" & sizeW & "||" & sizeH & "||" & enabledVal
                    end try
                end repeat
            end try
        end collectElements
    '''
    code, out, err = await _run_osascript(script)
    if code != 0:
        return {"success": False, "error": err or "accessibility_failed", "elements": []}
    elements: list[dict[str, Any]] = []
    frontmost_app = ""
    window_title = ""
    for line in str(out or "").splitlines():
        parts = line.split("||")
        if not parts:
            continue
        kind = str(parts[0] or "").strip().upper()
        if kind == "WINDOW":
            frontmost_app = str(parts[1] if len(parts) > 1 else "").strip()
            window_title = str(parts[2] if len(parts) > 2 else "").strip()
            continue
        if kind != "ELEMENT":
            continue
        role = str(parts[1] if len(parts) > 1 else "unknown").strip().lower() or "unknown"
        label = str(parts[2] if len(parts) > 2 else "").strip()
        entry: dict[str, Any] = {
            "label": label,
            "role": role,
            "source": "accessibility",
            "enabled": str(parts[7] if len(parts) > 7 else "true").strip().lower() != "false",
            "visible": True,
        }
        try:
            if len(parts) >= 7 and all(str(parts[idx]).strip() for idx in range(3, 7)):
                entry["x"] = int(parts[3])
                entry["y"] = int(parts[4])
                entry["width"] = int(parts[5])
                entry["height"] = int(parts[6])
        except Exception:
            pass
        if label or any(k in role for k in ("button", "text", "group")):
            elements.append(entry)
    return {
        "success": True,
        "frontmost_app": frontmost_app,
        "window_title": window_title,
        "elements": elements,
    }


async def _default_ocr(image_path: str) -> dict[str, Any]:
    target = str(image_path or "").strip()
    if not target:
        return {"success": False, "error": "ocr_missing_image"}
    tesseract = shutil.which("tesseract")
    if not tesseract:
        if _ensure_system_binary("tesseract"):
            tesseract = shutil.which("tesseract")
    if not tesseract:
        return {"success": False, "error": "ocr_unavailable", "text": "", "lines": []}
    proc = await asyncio.create_subprocess_exec(
        tesseract,
        target,
        "stdout",
        "tsv",
        "--psm",
        "6",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {"success": False, "error": stderr.decode("utf-8", errors="ignore").strip() or "ocr_failed", "text": "", "lines": []}
    rows = list(csv.DictReader(io.StringIO(stdout.decode("utf-8", errors="ignore")), delimiter="\t"))
    words: list[str] = []
    lines: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        conf = str(row.get("conf") or "").strip()
        if not text or conf == "-1":
            continue
        entry = {
            "text": text,
            "x": int(float(row.get("left") or 0)),
            "y": int(float(row.get("top") or 0)),
            "width": int(float(row.get("width") or 0)),
            "height": int(float(row.get("height") or 0)),
            "confidence": coerce_confidence(conf, 0.0),
            "source": "ocr",
        }
        lines.append(entry)
        words.append(text)
    return {"success": True, "text": " ".join(words).strip(), "lines": lines}


async def _default_vision(image_path: str, prompt: str) -> dict[str, Any]:
    json_prompt = (
        str(prompt or "").strip()
        + "\nReturn strict JSON with keys: summary, elements, risks."
        + " Elements must be a list of objects with label, role, confidence, x, y, width, height when visible."
        + " If uncertain, use empty arrays instead of prose outside JSON."
    )
    raw = await analyze_image(image_path, prompt=json_prompt)
    if not raw.get("success"):
        return {"success": False, "error": raw.get("error", "vision_failed"), "summary": "", "elements": []}
    analysis_text = str(raw.get("analysis") or raw.get("message") or "").strip()
    parsed: dict[str, Any] = {}
    for candidate in (analysis_text,):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                break
            except Exception:
                parsed = {}
    summary = str(parsed.get("summary") or analysis_text).strip()
    elements: list[dict[str, Any]] = []
    if isinstance(parsed.get("elements"), list):
        for item in parsed.get("elements"):
            if not isinstance(item, dict):
                continue
            row = {
                "label": str(item.get("label") or item.get("text") or "").strip(),
                "role": str(item.get("role") or item.get("kind") or "unknown").strip().lower() or "unknown",
                "confidence": coerce_confidence(item.get("confidence"), 0.45),
                "source": "vision",
            }
            for key in ("x", "y", "width", "height"):
                value = item.get(key)
                if isinstance(value, (int, float)):
                    row[key] = int(value)
            if row["label"] or any(k in row["role"] for k in ("button", "input", "field", "link")):
                elements.append(row)
    return {
        "success": True,
        "summary": summary,
        "elements": elements,
        "risks": list(parsed.get("risks") or []),
        "provider": str(raw.get("provider") or "vision"),
        "raw": raw,
    }


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(max(0.0, float(seconds or 0.0)))


async def _default_capture_region(*, x: int, y: int, width: int, height: int, filename: str | None = None) -> dict[str, Any]:
    from tools import system_tools

    return await system_tools.capture_region(x=x, y=y, width=width, height=height, filename=filename)


def default_screen_operator_services() -> ScreenOperatorServices:
    from tools import system_tools

    return ScreenOperatorServices(
        take_screenshot=system_tools.take_screenshot,
        capture_region=_default_capture_region,
        get_window_metadata=_default_window_metadata,
        get_accessibility_snapshot=_default_accessibility_snapshot,
        run_ocr=_default_ocr,
        run_vision=_default_vision,
        mouse_move=system_tools.mouse_move,
        mouse_click=system_tools.mouse_click,
        type_text=system_tools.type_text,
        press_key=system_tools.press_key,
        key_combo=system_tools.key_combo,
        sleep=_sleep,
    )


__all__ = ["ScreenOperatorServices", "default_screen_operator_services"]
