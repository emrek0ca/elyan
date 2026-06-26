"""
Medya oynatma — YouTube, Spotify Desktop ve Apple Music/Music uygulaması.
emre koca tarafından yapılmıştır — @emrekoca

Not:
- Spotify ve Music için otomatik oynatma best-effort yaklaşımıyla yapılır.
- Masaüstü uygulamalarında otomasyon için macOS Accessibility izni gerekebilir.
"""

from __future__ import annotations

import os
import subprocess
import urllib.parse

from actions._platform_common import (
    capability_unavailable,
    invalid_argument,
    is_macos,
    is_permission_detail,
    permission_required,
    unsupported_platform,
)
from actions.browser import browser_control


SPOTIFY_APP = "/Applications/Spotify.app"
MUSIC_APP = "/System/Applications/Music.app"


def _run_osascript(script: str, timeout: int = 16) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"AppleScript çalıştırılamadı: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "Bilinmeyen AppleScript hatası"
        return False, detail

    return True, (result.stdout or "").strip()


def _copy_to_clipboard(text: str) -> tuple[bool, str]:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=5)
        return True, "ok"
    except Exception as exc:
        return False, f"Panoya kopyalanamadı: {exc}"


def _app_exists(path: str) -> bool:
    return os.path.exists(path)


def _play_youtube(query: str) -> dict[str, object]:
    payload = browser_control("play_youtube", query=query)
    if isinstance(payload, str):
        return {
            "text": payload,
            "result": {
                "provider": "youtube",
                "autoplay": True,
                "query": query,
                "launched": True,
                "handoff": "browser_control",
                "handoffVerified": bool(query.strip()),
            },
        }
    result = payload.get("result")
    result = dict(result) if isinstance(result, dict) else {}
    result["provider"] = "youtube"
    result["autoplay"] = True
    result["query"] = query
    payload["result"] = result
    return payload


def _play_spotify(query: str, autoplay: bool = True) -> str:
    if not is_macos():
        raise unsupported_platform("Spotify masaustu oynatma su anda yalnizca macOS'ta destekleniyor.")
    if not _app_exists(SPOTIFY_APP):
        raise capability_unavailable("Spotify bu kurulumda hazir degil.")

    encoded_query = urllib.parse.quote(query.strip())
    search_url = f"spotify:search:{encoded_query}"

    try:
        subprocess.run(["open", search_url], check=True, timeout=10)
    except Exception as exc:
        raise capability_unavailable("Spotify guvenli sekilde acilamadi.") from exc

    if not autoplay:
        return f"Spotify içinde '{query}' araması açıldı."

    script = (
        'tell application "Spotify" to activate\n'
        "delay 1.8\n"
        'tell application "System Events"\n'
        "    key code 48\n"          # Tab
        "    delay 0.2\n"
        "    key code 125\n"         # Down
        "    delay 0.2\n"
        "    key code 36\n"          # Enter
        "    delay 0.5\n"
        "    key code 49\n"          # Space
        "end tell\n"
    )
    ok, detail = _run_osascript(script, timeout=14)
    if ok:
        return f"Spotify'da oynatılıyor: {query}"

    if is_permission_detail(detail):
        raise permission_required("Spotify otomasyonu icin erisilebilirlik izni gerekiyor.")
    raise capability_unavailable("Spotify oynatma otomasyonu guvenli sekilde tamamlanamadi.")


def _play_music_app(query: str, autoplay: bool = True) -> str:
    if not is_macos():
        raise unsupported_platform("Apple Music masaustu oynatma su anda yalnizca macOS'ta destekleniyor.")
    if not _app_exists(MUSIC_APP):
        raise capability_unavailable("Apple Music / Music bu kurulumda hazir degil.")

    if autoplay:
        escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'set queryText to "{escaped_query}"\n'
            'tell application "Music"\n'
            "    activate\n"
            "    try\n"
            "        set foundTracks to (search library playlist 1 for queryText only songs)\n"
            "        if (count of foundTracks) > 0 then\n"
            "            set targetTrack to item 1 of foundTracks\n"
            "            play targetTrack\n"
            "            return \"PLAYED\"\n"
            "        end if\n"
            "    end try\n"
            "end tell\n"
            "return \"NOT_FOUND\"\n"
        )
        ok, detail = _run_osascript(script, timeout=18)
        if ok and "PLAYED" in detail:
            return f"Music uygulamasında oynatılıyor: {query}"

    ok_clip, detail_clip = _copy_to_clipboard(query.strip())
    if not ok_clip:
        raise capability_unavailable("Music icin pano hazirlanamadi.")

    script = (
        'tell application "Music" to activate\n'
        "delay 1.0\n"
        'tell application "System Events"\n'
        '    keystroke "f" using {command down}\n'
        "    delay 0.3\n"
        '    keystroke "a" using {command down}\n'
        "    delay 0.1\n"
        '    keystroke "v" using {command down}\n'
        "    delay 1.1\n"
        "    key code 36\n"
        "    delay 0.7\n"
        "    key code 125\n"
        "    delay 0.2\n"
        "    key code 36\n"
        "end tell\n"
    )
    ok, detail = _run_osascript(script, timeout=16)
    if ok:
        if autoplay:
            return f"Music uygulamasında '{query}' için arama yapıldı ve ilk sonuç açıldı."
        return f"Music uygulamasında '{query}' araması açıldı."

    if is_permission_detail(detail):
        raise permission_required("Music otomasyonu icin erisilebilirlik izni gerekiyor.")
    search_url = f"music://music.apple.com/search?term={urllib.parse.quote(query.strip())}"
    try:
        subprocess.run(["open", search_url], check=False, timeout=10)
    except Exception:
        pass
    raise capability_unavailable("Music oynatma otomasyonu guvenli sekilde tamamlanamadi.")


def _media_result(text: str, *, provider: str, handoff: str, autoplay: bool, query: str) -> dict[str, object]:
    return {
        "text": text,
        "result": {
            "provider": provider,
            "handoff": handoff,
            "autoplay": autoplay,
            "query": query,
            "launched": True,
            "handoffVerified": bool(query.strip()),
        },
    }


def play_media(query: str, provider: str = "auto", autoplay: bool = True) -> dict[str, object]:
    if not query or not query.strip():
        raise invalid_argument("Calinacak icerik belirtilmedi.")

    normalized_provider = (provider or "auto").strip().lower()
    if normalized_provider in {"yt", "youtube music"}:
        normalized_provider = "youtube"
    elif normalized_provider in {"apple music", "music", "apple_music"}:
        normalized_provider = "apple_music"

    if normalized_provider == "spotify":
        if not is_macos():
            raise unsupported_platform("Spotify masaustu oynatma su anda yalnizca macOS'ta destekleniyor.")
        return _media_result(
            _play_spotify(query, autoplay=autoplay),
            provider="spotify",
            handoff="desktop_app",
            autoplay=autoplay,
            query=query,
        )
    if normalized_provider == "apple_music":
        if not is_macos():
            raise unsupported_platform("Apple Music masaustu oynatma su anda yalnizca macOS'ta destekleniyor.")
        return _media_result(
            _play_music_app(query, autoplay=autoplay),
            provider="apple_music",
            handoff="desktop_app",
            autoplay=autoplay,
            query=query,
        )
    if normalized_provider == "youtube":
        return _play_youtube(query)

    # auto: masaüstü müzik uygulamalarını dener, sonra YouTube'a düşer
    if not is_macos():
        return _play_youtube(query)
    if _app_exists(SPOTIFY_APP):
        try:
            return _media_result(
                _play_spotify(query, autoplay=autoplay),
                provider="spotify",
                handoff="desktop_app",
                autoplay=autoplay,
                query=query,
            )
        except Exception as exc:
            if getattr(exc, "code", "") not in {"CAPABILITY_UNAVAILABLE", "UNSUPPORTED_PLATFORM"}:
                raise
    try:
        return _media_result(
            _play_music_app(query, autoplay=autoplay),
            provider="apple_music",
            handoff="desktop_app",
            autoplay=autoplay,
            query=query,
        )
    except Exception as exc:
        if getattr(exc, "code", "") not in {"CAPABILITY_UNAVAILABLE", "UNSUPPORTED_PLATFORM"}:
            raise
    return _play_youtube(query)
