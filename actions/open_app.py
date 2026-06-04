"""
Uygulama açma ve kapatma — masaüstü kabiliyetleri.
emre koca tarafından yapılmıştır — @emrekoca
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from actions._platform_common import capability_unavailable, invalid_argument, require_macos, timeout_error

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None  # type: ignore[assignment]


# Kısa isimden uygulama yoluna eşleme
APP_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "finder": "Finder",
    "spotify": "Spotify",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "xcode": "Xcode",
    "notion": "Notion",
    "slack": "Slack",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "zoom": "zoom.us",
    "mail": "Mail",
    "calendar": "Calendar",
    "takvim": "Calendar",
    "notes": "Notes",
    "notlar": "Notes",
    "music": "Music",
    "müzik": "Music",
    "photos": "Photos",
    "fotoğraflar": "Photos",
    "maps": "Maps",
    "haritalar": "Maps",
    "calculator": "Calculator",
    "hesap makinesi": "Calculator",
    "system preferences": "System Preferences",
    "system settings": "System Settings",
    "ayarlar": "System Settings",
    "activity monitor": "Activity Monitor",
    "aktivite monitörü": "Activity Monitor",
    "preview": "Preview",
    "önizleme": "Preview",
    "textedit": "TextEdit",
    "numbers": "Numbers",
    "pages": "Pages",
    "keynote": "Keynote",
    "figma": "Figma",
    "postman": "Postman",
    "docker": "Docker",
    "sequel pro": "Sequel Pro",
    "tableplus": "TablePlus",
    "dosya gezgini": "Finder",
    "dosya yoneticisi": "Finder",
    "file explorer": "Finder",
    "file manager": "Finder",
}


def _resolve_app_name(app_name: str) -> str:
    normalized = app_name.lower().strip()
    return APP_ALIASES.get(normalized, app_name.strip())


def _looks_generic_close_target(app_name: str) -> bool:
    normalized = app_name.lower().strip()
    return normalized in {
        "",
        "app",
        "application",
        "program",
        "uygulama",
        "uygulamayi",
        "uygulamayı",
        "pencere",
    }


def _frontmost_application_name() -> str:
    snapshot_path = str(os.environ.get("ELYAN_DESKTOP_NATIVE_STATE_PATH", "") or "").strip()
    if snapshot_path:
        try:
            payload = json.loads(Path(snapshot_path).expanduser().read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                active_window = payload.get("activeWindow", {})
                if isinstance(active_window, dict):
                    app_name = str(active_window.get("appName", "") or "").strip()
                    if app_name:
                        return app_name
        except Exception:
            pass
    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _escape_osascript_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _terminate_matching_processes(target: str) -> int:
    if psutil is None:
        return 0

    normalized = target.lower().strip()
    if not normalized:
        return 0

    candidates = {
        normalized,
        normalized.replace(" ", ""),
        normalized.replace(".", ""),
    }
    matched: list[Any] = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            exe = str(proc.info.get("exe") or "").lower()
            cmdline = " ".join(str(item) for item in (proc.info.get("cmdline") or [])).lower()
            haystack = " ".join([name, exe, cmdline]).strip()
            if not haystack:
                continue
            if any(candidate and candidate in haystack for candidate in candidates):
                matched.append(proc)
        except Exception:
            continue

    if not matched:
        return 0

    for proc in matched:
        try:
            proc.terminate()
        except Exception:
            continue

    try:
        gone, alive = psutil.wait_procs(matched, timeout=3)
    except Exception:
        gone = []
        alive = matched

    for proc in alive:
        try:
            proc.kill()
        except Exception:
            continue

    return len(gone) + len(alive)


def open_app(app_name: str) -> str:
    """Uygulamayı açar, başarı/hata mesajı döndürür."""
    require_macos("Uygulama kontrolu")
    if not app_name:
        raise invalid_argument("Uygulama adi belirtilmedi.")

    resolved = _resolve_app_name(app_name)

    try:
        result = subprocess.run(
            ["open", "-a", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"{resolved} açıldı."

        # Spotlight ile dene
        result2 = subprocess.run(
            ["open", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.returncode == 0:
            return f"{app_name} açıldı."
        raise capability_unavailable(f"{resolved} bulunamadi veya guvenli sekilde acilamadi.")
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{resolved} acilirken zaman asimina ugradi.") from exc
    except Exception as exc:
        raise capability_unavailable(f"{resolved} guvenli sekilde acilamadi.") from exc


def close_app(app_name: str) -> str:
    """Uygulamayı güvenli şekilde kapatır."""
    require_macos("Uygulama kontrolu")
    resolved = _resolve_app_name(app_name) if app_name else ""
    if _looks_generic_close_target(app_name):
        resolved = _frontmost_application_name() or resolved
    if not resolved:
        raise invalid_argument("Kapatilacak uygulama bulunamadi.")

    script = f'tell application "{_escape_osascript_text(resolved)}" to quit'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"{resolved} kapatıldı."
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{resolved} kapatilirken zaman asimina ugradi.") from exc
    except Exception:
        pass

    terminated = _terminate_matching_processes(resolved)
    if terminated > 0:
        return f"{resolved} kapatıldı."

    raise capability_unavailable(f"{resolved} calisan bir uygulama olarak bulunamadi.")
