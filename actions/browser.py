from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser

import requests

from runtime.capability_registry import SafeCapabilityError

_VIDEO_ID_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_ALLOWED_ACTIONS = {"open_url", "search", "play_youtube", "new_tab"}

# "yeni sekme" isteğinde kullanıcının kastettiği tarayıcı adı → macOS uygulama
# adı. Bilinmeyen ad olduğu gibi denenir; boş istek varsayılan Chrome'dur
# (canlı arıza: 'Chrome dan yeni sekme aç' Google'da 'yeni sekme' ARAMASINA
# dönüşüyordu — sekme açmak arama değildir).
_BROWSER_APP_NAMES = {
    "": "Google Chrome",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "chromium": "Chromium",
    "brave": "Brave Browser",
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "safari": "Safari",
    "arc": "Arc",
}


def _open_new_tab(browser: str) -> str:
    """Belirtilen (ya da varsayılan) tarayıcıda YENİ SEKME açar; uygulama adını
    döndürür. macOS'ta AppleScript ile gerçek sekme açılır (pencere yoksa yeni
    pencere); diğer platformlarda varsayılan tarayıcıda boş sekmeye düşülür."""
    requested = str(browser or "").strip().lower()
    app_name = _BROWSER_APP_NAMES.get(requested, requested.title() or "Google Chrome")
    if sys.platform == "darwin":
        if app_name == "Safari":
            script = (
                'tell application "Safari"\n'
                "activate\n"
                "if (count of windows) = 0 then\n"
                "make new document\n"
                "else\n"
                "tell front window to set current tab to (make new tab)\n"
                "end if\n"
                "end tell"
            )
        else:
            script = (
                f'tell application "{app_name}"\n'
                "activate\n"
                "if (count of windows) = 0 then\n"
                "make new window\n"
                "else\n"
                "tell front window to make new tab at end of tabs\n"
                "end if\n"
                "end tell"
            )
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise SafeCapabilityError(
                "BROWSER_NEW_TAB_FAILED",
                f"{app_name} içinde yeni sekme açılamadı: {completed.stderr.strip()[:160] or 'osascript hatası'}",
            )
        return app_name
    webbrowser.open_new_tab("about:blank")
    return app_name


def _normalize_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise SafeCapabilityError("INVALID_ARGUMENT", "URL belirtilmedi.")
    if "://" not in value:
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Yalnız http veya https adresleri açılabilir.")
    return value


def _launch_url(url: str) -> None:
    try:
        controller = webbrowser.get()
        if controller.open(url, new=2):
            return
    except webbrowser.Error:
        pass

    if os.name == "nt" and hasattr(os, "startfile"):
        os.startfile(url)  # type: ignore[attr-defined]
        return
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.run([opener, url], check=False, timeout=10)
        return
    raise SafeCapabilityError(
        "UNSUPPORTED_PLATFORM",
        "Tarayıcı bu platformda güvenli şekilde açılamadı.",
    )


def _find_first_youtube_video(query: str) -> str | None:
    encoded = urllib.parse.quote_plus(query)
    response = requests.get(
        f"https://www.youtube.com/results?search_query={encoded}",
        headers={"User-Agent": "elyan/1.0"},
        timeout=10,
    )
    response.raise_for_status()

    seen: set[str] = set()
    for video_id in _VIDEO_ID_RE.findall(response.text):
        if video_id not in seen:
            seen.add(video_id)
            return video_id
    return None


def _browser_result(
    text: str,
    *,
    action: str,
    target_url: str = "",
    query: str = "",
    video_id: str = "",
    handoff: str = "browser",
) -> dict[str, object]:
    return {
        "text": text,
        "result": {
            "action": action,
            "targetUrl": target_url,
            "query": query,
            "videoId": video_id,
            "handoff": handoff,
            "launched": True,
            "handoffVerified": bool(target_url or query),
        },
    }


def browser_control(action: str, url: str = "", query: str = "", browser: str = "") -> dict[str, object]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _ALLOWED_ACTIONS:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz tarayıcı eylemi.")

    if normalized_action == "new_tab":
        app_name = _open_new_tab(browser)
        result = _browser_result(
            f"{app_name} içinde yeni sekme açıldı.",
            action="new_tab",
        )
        # new_tab'ın URL/sorgusu yoktur; kanıt AppleScript'in başarısı.
        inner = result.get("result")
        if isinstance(inner, dict):
            inner["handoffVerified"] = True
            inner["browserApp"] = app_name
        return result

    if normalized_action == "open_url":
        target_url = _normalize_url(url)
        _launch_url(target_url)
        return _browser_result(f"Açıldı: {target_url}", action="open_url", target_url=target_url)

    if normalized_action == "search":
        search_query = str(query or "").strip()
        if not search_query:
            raise SafeCapabilityError("INVALID_ARGUMENT", "Arama sorgusu belirtilmedi.")
        search_url = "https://www.google.com/search?q=" + urllib.parse.quote(search_query)
        _launch_url(search_url)
        return _browser_result(
            f"'{search_query}' için arama açıldı.",
            action="search",
            target_url=search_url,
            query=search_query,
        )

    youtube_query = str(query or "").strip()
    if not youtube_query:
        raise SafeCapabilityError("INVALID_ARGUMENT", "YouTube için arama sorgusu belirtilmedi.")

    try:
        video_id = _find_first_youtube_video(youtube_query)
    except Exception as exc:
        fallback_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(youtube_query)
        _launch_url(fallback_url)
        return _browser_result(
            (
                f"YouTube ilk sonucu alınamadı ({exc}). "
                f"Arama sonuçları açıldı: {youtube_query}"
            ),
            action="play_youtube",
            target_url=fallback_url,
            query=youtube_query,
            handoff="youtube_search_results",
        )

    if not video_id:
        fallback_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(youtube_query)
        _launch_url(fallback_url)
        return _browser_result(
            f"YouTube'da doğrudan video bulunamadı. Arama sonuçları açıldı: {youtube_query}",
            action="play_youtube",
            target_url=fallback_url,
            query=youtube_query,
            handoff="youtube_search_results",
        )

    watch_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
    _launch_url(watch_url)
    return _browser_result(
        f"YouTube'da oynatılıyor: {youtube_query}",
        action="play_youtube",
        target_url=watch_url,
        query=youtube_query,
        video_id=video_id,
        handoff="youtube_watch",
    )
