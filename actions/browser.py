from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
import webbrowser

import requests

from runtime.capability_registry import SafeCapabilityError

_VIDEO_ID_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')
_ALLOWED_ACTIONS = {"open_url", "search", "play_youtube"}


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


def browser_control(action: str, url: str = "", query: str = "") -> dict[str, object]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _ALLOWED_ACTIONS:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz tarayıcı eylemi.")

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
