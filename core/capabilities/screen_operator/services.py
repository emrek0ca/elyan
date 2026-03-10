from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from tools.vision_tools import analyze_image


AsyncDictCallable = Callable[..., Awaitable[dict[str, Any]]]


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
    if platform.system() != "Darwin":
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
    if platform.system() != "Darwin":
        return {"success": False, "error": "accessibility_unsupported", "elements": []}
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
            "confidence": max(0.0, min(float(conf or 0.0) / 100.0, 1.0)),
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
                "confidence": max(0.0, min(float(item.get("confidence") or 0.45), 1.0)),
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
