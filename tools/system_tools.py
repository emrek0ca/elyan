import asyncio
import json
import os
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


def _operator_step_timeout_s() -> float:
    raw = str(os.getenv("ELYAN_OPERATOR_STEP_TIMEOUT_S", "8")).strip()
    try:
        timeout = float(raw)
    except Exception:
        timeout = 8.0
    return max(0.5, min(timeout, 30.0))


def _operator_mission_timeout_s() -> float:
    raw = str(os.getenv("ELYAN_OPERATOR_MISSION_TIMEOUT_S", "45")).strip()
    try:
        timeout = float(raw)
    except Exception:
        timeout = 45.0
    return max(5.0, min(timeout, 300.0))


def _screen_vision_timeout_s() -> float:
    raw = str(os.getenv("ELYAN_SCREEN_VISION_TIMEOUT_S", "9")).strip()
    try:
        timeout = float(raw)
    except Exception:
        timeout = 9.0
    return max(0.1, min(timeout, 30.0))


async def _await_operator_budget(coro, *, timeout_s: float, label: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"success": False, "error": f"{label}_timeout:{timeout_s:.1f}s", "error_code": f"{label}_timeout"}


async def _analyze_image_with_timeout(shot_path: str, prompt_text: str) -> dict[str, Any]:
    from tools.vision_tools import analyze_image

    timeout_s = _screen_vision_timeout_s()
    try:
        return await asyncio.wait_for(
            analyze_image(shot_path, prompt=prompt_text),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("Vision analyze timeout after %.1fs for screenshot: %s", timeout_s, shot_path)
        return {
            "success": False,
            "error": f"vision_timeout:{timeout_s:.1f}s",
            "provider": "ollama/llava",
            "error_code": "vision_timeout",
        }


def _normalize_screen_analysis_payload(analysis: Dict[str, Any], shot_path: str) -> Dict[str, Any]:
    provider = str(analysis.get("provider") or "").strip()
    summary = str(analysis.get("summary") or analysis.get("analysis") or "").strip()
    mode = str(analysis.get("analysis_mode") or "").strip()
    if not mode:
        mode = "fallback" if provider.startswith("fallback/") else "vision"

    result: Dict[str, Any] = {
        "success": bool(analysis.get("success")),
        "path": str(analysis.get("path") or shot_path or "").strip(),
        "summary": summary,
        "ocr": analysis.get("ocr", ""),
        "objects": analysis.get("objects", []),
        "risks": analysis.get("risks", []),
        "provider": provider,
        "error": analysis.get("error", ""),
        "analysis_mode": mode,
    }

    warning = str(analysis.get("warning") or "").strip()
    if warning:
        result["warning"] = warning

    status_report = analysis.get("status_report")
    if isinstance(status_report, dict):
        result["status_report"] = status_report
    ui_map = analysis.get("ui_map")
    if isinstance(ui_map, dict):
        result["ui_map"] = ui_map

    return result


def _extract_quoted_text(raw: str) -> str:
    text = str(raw or "")
    m = re.search(r"['\"]([^'\"]{2,280})['\"]", text)
    return str(m.group(1) or "").strip() if m else ""


_APP_NAME_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "krom": "Google Chrome",
    "firefox": "Firefox",
    "arc": "Arc",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "discord": "Discord",
    "slack": "Slack",
    "finder": "Finder",
    "terminal": "Terminal",
    "cursor": "Cursor",
    "vscode": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "notes": "Notes",
    "notlar": "Notes",
    "mail": "Mail",
    "spotify": "Spotify",
    "preview": "Preview",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "teams": "Microsoft Teams",
    "zoom": "zoom.us",
}
_BROWSER_APPS = {"Safari", "Google Chrome", "Firefox", "Arc"}
_APP_OPERATOR_PROFILES: dict[str, dict[str, Any]] = {
    "Safari": {
        "category": "browser",
        "launch_wait_s": 0.9,
        "resource_lane": "browser",
        "verify_markers": ["safari", "browser", "tab", "address bar"],
        "preferred_search_engine": "google",
    },
    "Google Chrome": {
        "category": "browser",
        "launch_wait_s": 0.9,
        "resource_lane": "browser",
        "verify_markers": ["chrome", "browser", "tab", "address bar"],
        "preferred_search_engine": "google",
    },
    "Arc": {
        "category": "browser",
        "launch_wait_s": 1.0,
        "resource_lane": "browser",
        "verify_markers": ["arc", "browser", "tab", "sidebar"],
        "preferred_search_engine": "google",
    },
    "Finder": {"category": "filesystem", "launch_wait_s": 0.7, "resource_lane": "filesystem", "verify_markers": ["finder", "folder", "desktop", "downloads"]},
    "Mail": {"category": "mail", "launch_wait_s": 1.0, "resource_lane": "mail", "verify_markers": ["mail", "inbox", "message", "mailbox"]},
    "Cursor": {"category": "ide", "launch_wait_s": 1.0, "resource_lane": "ide", "verify_markers": ["cursor", "editor", "workspace", "terminal"]},
    "Visual Studio Code": {"category": "ide", "launch_wait_s": 1.0, "resource_lane": "ide", "verify_markers": ["code", "editor", "workspace", "terminal"]},
    "Terminal": {"category": "terminal", "launch_wait_s": 0.8, "resource_lane": "terminal", "verify_markers": ["terminal", "shell", "command", "prompt"]},
    "Telegram": {"category": "messaging", "launch_wait_s": 1.0, "resource_lane": "messaging", "verify_markers": ["telegram", "chat", "message"]},
    "WhatsApp": {"category": "messaging", "launch_wait_s": 1.0, "resource_lane": "messaging", "verify_markers": ["whatsapp", "chat", "message"]},
}


def _get_app_operator_profile(app_name: str) -> dict[str, Any]:
    normalized = str(app_name or "").strip()
    if not normalized:
        return {"category": "generic", "launch_wait_s": 0.7, "resource_lane": "generic", "verify_markers": []}
    profile = _APP_OPERATOR_PROFILES.get(normalized)
    if isinstance(profile, dict):
        return dict(profile)
    return {
        "category": "generic",
        "launch_wait_s": 0.7,
        "resource_lane": "generic",
        "verify_markers": [_normalize_text_for_match(normalized)],
    }


_APP_ALIAS_SUFFIX_PATTERN = (
    r"(?:['’]?(?:i|ı|u|ü|yi|yı|yu|yü|e|a|ye|ya|de|da|te|ta|den|dan|ten|tan|nin|nın|nun|nün|in|ın|un|ün|le|la))?"
)


def _extract_target_app(goal: str) -> str:
    low = _normalize_text_for_match(goal)
    for alias in sorted(_APP_NAME_ALIASES.keys(), key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}{_APP_ALIAS_SUFFIX_PATTERN}(?![a-z0-9])"
        if re.search(pattern, low):
            return _APP_NAME_ALIASES[alias]
    return ""


def _strip_operator_noise(goal: str, *, target_app: str = "") -> str:
    text = _normalize_text_for_match(goal)
    if not text:
        return ""
    noise = [
        "ekrana bak", "ekrani oku", "ekrani kontrol et", "ekrani kullan", "ekrani yonet",
        "bilgisayari kullan", "bilgisayari kontrol et", "bilgisayari yonet",
        "aç", "ac", "open", "launch", "başlat", "baslat", "çalıştır", "calistir",
        "kapat", "close", "quit", "tıkla", "tikla", "click", "yaz", "type", "gir",
        "seç", "sec", "ara", "search", "arama yap", "göster", "goster", "durum nedir",
        "enter", "gonder", "gönder", "ve", "sonra", "ardindan", "ardından",
    ]
    alias_terms = list(_APP_NAME_ALIASES.keys())
    if target_app:
        alias_terms.append(_normalize_text_for_match(target_app))
    for term in sorted(noise + alias_terms, key=len, reverse=True):
        if not term:
            continue
        text = re.sub(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", " ", text)
    return " ".join(text.split()).strip()


def _build_operator_goal_profile(goal: str) -> dict[str, Any]:
    normalized_goal = _normalize_text_for_match(goal)
    typed_text = _extract_quoted_text(goal)
    target_app = _extract_target_app(goal)
    app_profile = _get_app_operator_profile(target_app)
    target_url_match = re.search(r"https?://\S+", str(goal or ""), flags=re.IGNORECASE)
    target_url = str(target_url_match.group(0) or "").strip() if target_url_match else ""
    click_points = _extract_coordinate_candidates(goal)

    wants_open = any(k in normalized_goal for k in (" ac", "aç", " open ", "launch", "baslat", "başlat"))
    wants_close = any(k in normalized_goal for k in ("kapat", "close", "quit", "sonlandir", "sonlandır"))
    wants_click = any(k in normalized_goal for k in ("tikla", "tıkla", "click", "sec", "seç", "bas"))
    wants_type = bool(typed_text) or any(k in normalized_goal for k in (" yaz", "type", "gir "))
    wants_submit = any(k in normalized_goal for k in ("enter", "gonder", "gönder", "submit", "ara", "search"))
    wants_search = any(k in normalized_goal for k in ("ara", "search", "google", "arama yap", "arastir", "araştır", "resim", "image"))
    wants_save = any(k in normalized_goal for k in ("kaydet", "save", "indir", "download"))
    wants_read = any(
        k in normalized_goal
        for k in ("ekrana bak", "ekrani oku", "durum nedir", "ekranda ne var", "kontrol et", "incele", "analiz et")
    )
    read_only = wants_read and not any((wants_open, wants_close, wants_click, wants_type, wants_search, wants_save, target_url))

    browser_app = target_app if target_app in _BROWSER_APPS else "Safari"
    stripped = _strip_operator_noise(goal, target_app=target_app)
    search_query = stripped or typed_text
    if wants_search and not search_query:
        search_query = str(goal or "").strip()

    verification_markers: list[str] = []
    if target_app:
        verification_markers.append(_normalize_text_for_match(target_app))
    for marker in list(app_profile.get("verify_markers") or []):
        clean_marker = _normalize_text_for_match(str(marker or ""))
        if clean_marker:
            verification_markers.append(clean_marker)
    for blob in (typed_text, search_query):
        if not blob:
            continue
        verification_markers.extend(re.findall(r"[a-z0-9]{3,}", _normalize_text_for_match(blob))[:4])
    if target_url:
        verification_markers.append(_normalize_text_for_match(target_url))

    return {
        "goal": str(goal or "").strip(),
        "normalized_goal": normalized_goal,
        "target_app": target_app,
        "app_profile": app_profile,
        "launch_wait_s": float(app_profile.get("launch_wait_s", 0.7) or 0.7),
        "browser_app": browser_app,
        "target_url": target_url,
        "typed_text": typed_text,
        "search_query": search_query,
        "coordinate_targets": click_points,
        "wants_open": wants_open,
        "wants_close": wants_close,
        "wants_click": wants_click,
        "wants_type": wants_type,
        "wants_submit": wants_submit,
        "wants_search": wants_search,
        "wants_save": wants_save,
        "wants_read": wants_read,
        "read_only": read_only,
        "verification_markers": [m for m in list(dict.fromkeys(verification_markers)) if m][:8],
    }


def _split_operator_objectives(objective: str, *, max_items: int = 4) -> list[str]:
    text = str(objective or "").strip()
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text).strip()
    numbered = re.split(r"(?:^|\s)\d+\)\s*", normalized)
    if len([chunk for chunk in numbered if chunk.strip()]) >= 2:
        parts = [chunk.strip(" ,;") for chunk in numbered if chunk.strip()]
        return parts[: max(1, int(max_items or 1))]
    parts = re.split(r"\b(?:ardından|ardindan|sonra|then|ve sonra)\b", normalized, flags=re.IGNORECASE)
    cleaned = [part.strip(" ,;") for part in parts if part.strip(" ,;")]
    return cleaned[: max(1, int(max_items or 1))]


def _parallelizable_operator_groups(objectives: list[str]) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    for idx, item in enumerate(objectives, start=1):
        profile = _build_operator_goal_profile(item)
        if str(_operator_execution_class(profile)) == "inspect":
            current.append(idx)
            continue
        if len(current) >= 2:
            groups.append(list(current))
        current = []
    if len(current) >= 2:
        groups.append(list(current))
    return groups


def _step_signature(step: dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""
    action = str(step.get("action") or "").strip().lower()
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    try:
        payload = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = str(params)
    return f"{action}:{payload}"


_OPERATOR_MUTATION_LOCK: Optional[asyncio.Lock] = None


def _operator_execution_class(profile: dict[str, Any]) -> str:
    if not isinstance(profile, dict):
        return "mutating_control"
    if bool(profile.get("read_only")):
        return "inspect"
    return "mutating_control"


def _operator_execution_lane(profile: dict[str, Any]) -> str:
    if not isinstance(profile, dict):
        return "generic"
    app_profile = profile.get("app_profile") if isinstance(profile.get("app_profile"), dict) else {}
    lane = str(app_profile.get("resource_lane") or "").strip().lower()
    if lane:
        return lane
    if bool(profile.get("wants_search")) or str(profile.get("target_url") or "").strip():
        return "browser"
    target_app = str(profile.get("target_app") or "").strip()
    if target_app:
        return _normalize_text_for_match(target_app).replace(" ", "_")
    return "generic"


def _build_operator_scheduler_plan(objectives: list[str]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for idx, objective in enumerate(objectives, start=1):
        profile = _build_operator_goal_profile(objective)
        execution_class = _operator_execution_class(profile)
        execution_lane = _operator_execution_lane(profile)
        plan.append(
            {
                "index": idx,
                "objective": objective,
                "execution_class": execution_class,
                "execution_lane": execution_lane,
                "can_run_parallel": execution_class == "inspect",
                "blocking_reason": "" if execution_class == "inspect" else "shared_operator_surface",
            }
        )
    return plan


def _init_operator_lane_states(scheduler_plan: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for item in list(scheduler_plan or []):
        if not isinstance(item, dict):
            continue
        lane = str(item.get("execution_lane") or "generic").strip().lower() or "generic"
        if lane in states:
            continue
        states[lane] = {
            "status": "healthy",
            "failures": 0,
            "recovery_attempts": 0,
            "last_objective": "",
            "last_recovery_summary": "",
        }
    return states


def _analysis_marker_hits(analysis: dict[str, Any], markers: list[str]) -> dict[str, Any]:
    hay = " ".join(
        [
            _normalize_text_for_match(str(analysis.get("summary") or "")),
            _normalize_text_for_match(str(analysis.get("ocr") or "")),
            _normalize_text_for_match(json.dumps(analysis.get("objects", []), ensure_ascii=False)),
            _normalize_text_for_match(json.dumps(analysis.get("ui_map", {}), ensure_ascii=False)),
        ]
    )
    clean_markers = [str(m).strip() for m in list(dict.fromkeys(markers or [])) if str(m).strip()]
    hits = [marker for marker in clean_markers if marker in hay]
    return {"haystack": hay, "markers": clean_markers, "hits": hits}


def _build_operator_lane_expected_markers(lane: str, profile: dict[str, Any]) -> list[str]:
    lane_name = str(lane or "generic").strip().lower() or "generic"
    target_app = _normalize_text_for_match(str(profile.get("target_app") or ""))
    browser_app = _normalize_text_for_match(str(profile.get("browser_app") or ""))
    app_profile = profile.get("app_profile") if isinstance(profile.get("app_profile"), dict) else {}
    markers: list[str] = []
    if lane_name == "browser":
        markers.extend(["browser", "tab", "address bar"])
    elif lane_name == "mail":
        markers.extend(["mail", "inbox", "mailbox"])
    elif lane_name == "ide":
        markers.extend(["editor", "workspace", "terminal"])
    elif lane_name == "filesystem":
        markers.extend(["finder", "folder", "desktop"])
    elif lane_name == "terminal":
        markers.extend(["terminal", "shell", "prompt"])
    elif lane_name == "messaging":
        markers.extend(["chat", "message"])

    if target_app:
        markers.append(target_app)
    if browser_app and lane_name == "browser":
        markers.append(browser_app)
    for marker in list(app_profile.get("verify_markers") or []):
        normalized = _normalize_text_for_match(str(marker or ""))
        if normalized:
            markers.append(normalized)
    return [m for m in list(dict.fromkeys(markers)) if m][:8]


def _lane_probe_matches(lane: str, profile: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    expected_markers = _build_operator_lane_expected_markers(lane, profile)
    marker_eval = _analysis_marker_hits(analysis, expected_markers)
    target_app = _normalize_text_for_match(str(profile.get("target_app") or ""))
    fallback_app = _normalize_text_for_match(str(profile.get("browser_app") or ""))
    target_focus = target_app or (fallback_app if str(lane or "").strip().lower() == "browser" else "")
    ui_map = analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}
    frontmost_app = _normalize_text_for_match(str(ui_map.get("frontmost_app") or ""))
    focus_match = bool(target_focus) and frontmost_app == target_focus
    hit_count = len(list(marker_eval.get("hits") or []))
    app_identity_markers = {m for m in (target_app, fallback_app) if m}
    structural_hits = [hit for hit in list(marker_eval.get("hits") or []) if hit not in app_identity_markers]
    marker_match = hit_count >= 2 or (focus_match and len(structural_hits) >= 1) or (focus_match and not expected_markers)
    return {
        "expected_markers": expected_markers,
        "marker_hits": list(marker_eval.get("hits") or []),
        "structural_hits": structural_hits,
        "frontmost_app": frontmost_app,
        "focus_match": focus_match,
        "marker_match": marker_match,
    }


async def _probe_operator_lane(
    lane: str,
    objective: str,
    profile: dict[str, Any],
    *,
    timeout_s: float,
) -> dict[str, Any]:
    lane_name = str(lane or "generic").strip().lower() or "generic"
    target_app = str(profile.get("target_app") or "").strip()
    prompt = (
        f"Lane recovery probe. Lane: {lane_name}. Hedef gorev: {objective}. "
        f"Hedef uygulama: {target_app or 'genel'}. "
        "Ekranin bu lane icin hazir olup olmadigini, aktif uygulamayi ve kisa riskleri ozetle."
    )
    res = await _await_operator_budget(
        analyze_screen(prompt=prompt),
        timeout_s=min(max(0.05, float(timeout_s or 0.0)), _operator_step_timeout_s()),
        label="operator_lane_probe",
    )
    marker_eval = _lane_probe_matches(lane_name, profile, res)
    summary = str(res.get("summary") or res.get("message") or "").strip()
    path = str(res.get("path") or "").strip()
    return {
        "lane": lane_name,
        "objective": objective,
        "success": bool(res.get("success")) and bool(marker_eval.get("marker_match")),
        "summary": summary,
        "path": path,
        "expected_markers": list(marker_eval.get("expected_markers") or []),
        "marker_hits": list(marker_eval.get("marker_hits") or []),
        "frontmost_app": str(marker_eval.get("frontmost_app") or ""),
        "focus_match": bool(marker_eval.get("focus_match")),
        "marker_match": bool(marker_eval.get("marker_match")),
        "raw_result": res,
    }


def _build_operator_lane_recovery_steps(lane: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    lane_name = str(lane or "generic").strip().lower() or "generic"
    target_app = str(profile.get("target_app") or "").strip()
    browser_app = str(profile.get("browser_app") or "").strip() or "Safari"
    launch_wait_s = max(0.2, min(2.0, float(profile.get("launch_wait_s", 0.7) or 0.7)))
    app_to_focus = target_app or browser_app or "Safari"

    if lane_name == "browser":
        return [
            {"action": "open_app", "params": {"app_name": browser_app}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "key_combo", "params": {"combo": "cmd+l"}},
            {"action": "wait", "params": {"seconds": 0.2}},
        ]
    if lane_name == "mail":
        return [
            {"action": "open_app", "params": {"app_name": target_app or "Mail"}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "key_combo", "params": {"combo": "cmd+1"}},
            {"action": "wait", "params": {"seconds": 0.2}},
        ]
    if lane_name == "ide":
        return [
            {"action": "open_app", "params": {"app_name": target_app or "Cursor"}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "press_key", "params": {"key": "escape"}},
        ]
    if lane_name == "filesystem":
        return [
            {"action": "open_app", "params": {"app_name": target_app or "Finder"}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "press_key", "params": {"key": "escape"}},
        ]
    if lane_name == "terminal":
        return [
            {"action": "open_app", "params": {"app_name": target_app or "Terminal"}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "press_key", "params": {"key": "escape"}},
        ]
    if lane_name == "messaging":
        return [
            {"action": "open_app", "params": {"app_name": target_app or "Telegram"}},
            {"action": "wait", "params": {"seconds": launch_wait_s}},
            {"action": "press_key", "params": {"key": "escape"}},
        ]
    return [
        {"action": "open_app", "params": {"app_name": app_to_focus}},
        {"action": "wait", "params": {"seconds": launch_wait_s}},
    ]


async def _run_operator_lane_recovery(
    lane: str,
    objective: str,
    profile: dict[str, Any],
    *,
    timeout_s: float,
) -> dict[str, Any]:
    steps = _build_operator_lane_recovery_steps(lane, profile)
    if not steps:
        return {
            "lane": str(lane or "generic").strip().lower() or "generic",
            "objective": objective,
            "success": True,
            "steps": [],
            "screenshots": [],
            "message": "no_recovery_steps",
        }
    res = await _await_operator_budget(
        computer_use(
            steps=steps,
            goal=f"lane_recovery:{lane}:{objective}",
            auto_plan=False,
            final_screenshot=False,
            screenshot_after_each=False,
            vision_feedback=False,
            max_feedback_loops=0,
        ),
        timeout_s=max(0.05, float(timeout_s or 0.0)),
        label="operator_lane_recovery",
    )
    return {
        "lane": str(lane or "generic").strip().lower() or "generic",
        "objective": objective,
        "success": bool(res.get("success")),
        "steps": steps,
        "screenshots": list(res.get("screenshots") or []),
        "message": str(res.get("message") or res.get("error") or "").strip(),
        "raw_result": res,
    }


def _get_operator_mutation_lock() -> asyncio.Lock:
    global _OPERATOR_MUTATION_LOCK
    if _OPERATOR_MUTATION_LOCK is None:
        _OPERATOR_MUTATION_LOCK = asyncio.Lock()
    return _OPERATOR_MUTATION_LOCK


def _goal_to_computer_steps(goal: str) -> list[dict[str, Any]]:
    profile = _build_operator_goal_profile(goal)
    low = str(goal or "").strip().lower()
    if not low or profile["read_only"]:
        return []

    steps: list[dict[str, Any]] = []
    browser = str(profile.get("browser_app") or "Safari")
    app_profile = profile.get("app_profile") if isinstance(profile.get("app_profile"), dict) else {}
    launch_wait_s = max(0.2, min(2.0, float(profile.get("launch_wait_s", 0.7) or 0.7)))
    target_app = str(profile.get("target_app") or "")
    typed = str(profile.get("typed_text") or "")
    query = str(profile.get("search_query") or "").strip()
    target_url = str(profile.get("target_url") or "").strip()
    coordinate_targets = list(profile.get("coordinate_targets") or [])

    if bool(profile.get("wants_close")) and target_app:
        return [
            {"action": "close_app", "params": {"app_name": target_app}},
            {"action": "wait", "params": {"seconds": min(0.6, launch_wait_s)}},
        ]

    if target_url:
        steps.extend(
            [
                {"action": "open_app", "params": {"app_name": browser}},
                {"action": "wait", "params": {"seconds": launch_wait_s}},
                {"action": "open_url", "params": {"url": target_url, "browser": browser}},
                {"action": "wait", "params": {"seconds": max(0.9, launch_wait_s)}},
            ]
        )
    elif bool(profile.get("wants_search")):
        query = query or str(goal or "").strip()
        tbm = "isch" if any(k in low for k in ("resim", "image", "fotoğraf", "fotograf", "wallpaper", "duvar kağıdı")) else ""
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        if tbm:
            url += f"&tbm={tbm}"
        steps.extend(
            [
                {"action": "open_app", "params": {"app_name": browser}},
                {"action": "open_url", "params": {"url": url, "browser": browser}},
                {"action": "wait", "params": {"seconds": max(1.0, launch_wait_s)}},
            ]
        )

    if target_app and not any(step.get("action") == "open_app" for step in steps):
        if bool(profile.get("wants_open")) or bool(profile.get("wants_type")) or bool(profile.get("wants_click")):
            steps.extend(
                [
                    {"action": "open_app", "params": {"app_name": target_app}},
                    {"action": "wait", "params": {"seconds": launch_wait_s}},
                ]
            )

    if target_app == "Terminal" and (typed or query):
        text_to_type = typed or query
        steps.append({"action": "type_text", "params": {"text": text_to_type, "press_enter": True}})
    elif typed:
        steps.append({"action": "type_text", "params": {"text": typed, "press_enter": bool(profile.get("wants_submit"))}})
    elif bool(profile.get("wants_type")) and query and not bool(profile.get("wants_search")):
        steps.append({"action": "type_text", "params": {"text": query, "press_enter": bool(profile.get("wants_submit"))}})

    if (
        bool(profile.get("wants_open"))
        and not typed
        and not bool(profile.get("wants_type"))
        and not bool(profile.get("wants_submit"))
        and str(app_profile.get("category") or "") == "mail"
    ):
        steps.append({"action": "press_key", "params": {"key": "enter"}})

    if bool(profile.get("wants_click")) and coordinate_targets:
        point = coordinate_targets[0]
        steps.append({"action": "mouse_click", "params": {"x": int(point["x"]), "y": int(point["y"])}})

    if bool(profile.get("wants_submit")) and not any(step.get("action") == "type_text" and step.get("params", {}).get("press_enter") for step in steps):
        steps.append({"action": "press_key", "params": {"key": "enter"}})

    if bool(profile.get("wants_save")):
        steps.extend(
            [
                {"action": "key_combo", "params": {"combo": "cmd+s"}},
                {"action": "wait", "params": {"seconds": 0.5}},
            ]
        )

    if any(k in low for k in ("terminal", "komut", "command")):
        terminal_wait_s = max(0.2, min(2.0, float(_get_app_operator_profile("Terminal").get("launch_wait_s", 0.8) or 0.8)))
        steps = [{"action": "open_app", "params": {"app_name": "Terminal"}}, {"action": "wait", "params": {"seconds": terminal_wait_s}}] + steps

    # Fallback baseline for generic computer-control intent.
    if not steps:
        if target_app:
            steps = [
                {"action": "open_app", "params": {"app_name": target_app}},
                {"action": "wait", "params": {"seconds": launch_wait_s}},
            ]
        elif coordinate_targets and bool(profile.get("wants_click")):
            point = coordinate_targets[0]
            steps = [{"action": "mouse_click", "params": {"x": int(point["x"]), "y": int(point["y"])}}]
        else:
            steps = [
                {"action": "open_app", "params": {"app_name": browser}},
                {"action": "wait", "params": {"seconds": launch_wait_s}},
            ]
    return steps


async def _run_operator_subtask(
    objective: str,
    *,
    pause_ms: int,
    timeout_s: float,
    execution_mode: str = "serial",
) -> dict[str, Any]:
    profile = _build_operator_goal_profile(objective)
    execution_class = _operator_execution_class(profile)
    execution_lane = _operator_execution_lane(profile)
    mode = "inspect" if execution_class == "inspect" else "control"
    timeout_budget = max(0.05, float(timeout_s or 0.0))
    res: dict[str, Any]
    artifacts: list[str] = []
    if mode == "inspect":
        res = await _await_operator_budget(
            analyze_screen(prompt=f"Gorev: {objective}. Bu gorev acisindan ekrani kisa ozetle."),
            timeout_s=min(timeout_budget, _operator_step_timeout_s()),
            label="operator_inspect",
        )
        message = str(res.get("summary") or res.get("message") or "").strip()
        goal_achieved = bool(res.get("success"))
        path = str(res.get("path") or "").strip()
        if path:
            artifacts.append(path)
    else:
        async with _get_operator_mutation_lock():
            res = await _await_operator_budget(
                vision_operator_loop(objective, max_iterations=2, pause_ms=pause_ms, include_ui_map=True),
                timeout_s=timeout_budget,
                label="operator_subtask",
            )
        message = str(res.get("message") or "").strip()
        goal_achieved = bool(res.get("goal_achieved"))
        for shot in list(res.get("screenshots", []) or []):
            shot_path = str(shot or "").strip()
            if shot_path:
                artifacts.append(shot_path)

    return {
        "objective": objective,
        "mode": mode,
        "profile": profile,
        "success": bool(res.get("success")),
        "goal_achieved": bool(goal_achieved),
        "message": message,
        "artifacts": artifacts,
        "execution_mode": execution_mode,
        "execution_class": execution_class,
        "execution_lane": execution_lane,
        "raw_result": res,
    }


@tool("operator_mission_control", "Plan and execute multi-step operator missions on the computer.")
async def operator_mission_control(
    objective: str,
    max_subtasks: int = 4,
    pause_ms: int = 250,
) -> dict[str, Any]:
    try:
        mission = str(objective or "").strip()
        if not mission:
            return {"success": False, "error": "objective gerekli."}
        started_at = time.monotonic()
        mission_timeout_s = _operator_mission_timeout_s()

        subtasks = _split_operator_objectives(mission, max_items=max_subtasks)
        scheduler_plan = _build_operator_scheduler_plan(subtasks)
        lane_statuses = _init_operator_lane_states(scheduler_plan)
        lane_recovery_attempts: list[dict[str, Any]] = []
        if len(subtasks) <= 1:
            single_profile = _build_operator_goal_profile(mission)
            single = await _await_operator_budget(
                vision_operator_loop(mission, max_iterations=2, pause_ms=pause_ms, include_ui_map=True),
                timeout_s=mission_timeout_s,
                label="operator_mission",
            )
            single["subtasks"] = [
                {
                    "index": 1,
                    "objective": mission,
                    "success": bool(single.get("success")),
                    "goal_achieved": bool(single.get("goal_achieved")),
                    "summary": str(single.get("message") or ""),
                    "mode": "inspect" if bool(single_profile.get("read_only")) else "control",
                    "execution_class": _operator_execution_class(single_profile),
                    "execution_lane": _operator_execution_lane(single_profile),
                    "execution_mode": "serial",
                }
            ]
            single["mission"] = mission
            single["parallelizable_groups"] = []
            single["executed_parallel_groups"] = []
            single["scheduler_plan"] = scheduler_plan
            single["lane_statuses"] = lane_statuses
            single["lane_recovery_attempts"] = lane_recovery_attempts
            return single

        reports: list[dict[str, Any]] = []
        artifacts: list[str] = []
        completed = 0
        next_action = ""
        overall_success = True
        parallelizable_groups = _parallelizable_operator_groups(subtasks)
        group_lookup = {group[0]: list(group) for group in parallelizable_groups if group}
        executed_parallel_groups: list[list[int]] = []

        idx = 1
        while idx <= len(subtasks):
            item = subtasks[idx - 1]
            if (time.monotonic() - started_at) >= mission_timeout_s:
                overall_success = False
                next_action = item
                reports.append(
                    {
                        "index": idx,
                        "objective": item,
                        "mode": "pending",
                        "success": False,
                        "goal_achieved": False,
                        "summary": f"operator_mission_timeout:{mission_timeout_s:.1f}s",
                        "task_model": _build_operator_goal_profile(item),
                        "execution_class": _operator_execution_class(_build_operator_goal_profile(item)),
                        "execution_lane": _operator_execution_lane(_build_operator_goal_profile(item)),
                        "execution_mode": "timeout",
                    }
                )
                break

            group = group_lookup.get(idx, [])
            if len(group) >= 2:
                remaining_budget = max(1.0, mission_timeout_s - (time.monotonic() - started_at))
                batch = await asyncio.gather(
                    *[
                        _run_operator_subtask(
                            subtasks[group_idx - 1],
                            pause_ms=pause_ms,
                            timeout_s=remaining_budget,
                            execution_mode="parallel_inspect",
                        )
                        for group_idx in group
                    ],
                    return_exceptions=True,
                )
                executed_parallel_groups.append(list(group))
                for group_idx, batch_item in zip(group, batch):
                    objective_text = subtasks[group_idx - 1]
                    if isinstance(batch_item, Exception):
                        profile = _build_operator_goal_profile(objective_text)
                        reports.append(
                            {
                                "index": group_idx,
                                "objective": objective_text,
                                "mode": "inspect" if bool(profile.get("read_only")) else "control",
                                "success": False,
                                "goal_achieved": False,
                                "summary": str(batch_item),
                                "task_model": profile,
                                "execution_class": _operator_execution_class(profile),
                                "execution_lane": _operator_execution_lane(profile),
                                "execution_mode": "parallel_inspect",
                            }
                        )
                        overall_success = False
                        if not next_action:
                            next_action = objective_text
                        break

                    batch_success = bool(batch_item.get("success")) and bool(batch_item.get("goal_achieved") or batch_item.get("mode") == "inspect")
                    reports.append(
                        {
                            "index": group_idx,
                            "objective": objective_text,
                            "mode": str(batch_item.get("mode") or "inspect"),
                            "success": bool(batch_item.get("success")),
                            "goal_achieved": bool(batch_item.get("goal_achieved")),
                            "summary": str(batch_item.get("message") or ""),
                            "task_model": batch_item.get("profile"),
                            "execution_class": str(batch_item.get("execution_class") or ""),
                            "execution_lane": str(batch_item.get("execution_lane") or ""),
                            "execution_mode": str(batch_item.get("execution_mode") or "parallel_inspect"),
                        }
                    )
                    for shot_path in list(batch_item.get("artifacts") or []):
                        if shot_path:
                            artifacts.append(str(shot_path))
                    if batch_success:
                        completed += 1
                        continue
                    overall_success = False
                    if not next_action:
                        next_action = objective_text
                idx = group[-1] + 1
                continue

            remaining_budget = max(1.0, mission_timeout_s - (time.monotonic() - started_at))
            profile = _build_operator_goal_profile(item)
            execution_lane = _operator_execution_lane(profile)
            execution_class = _operator_execution_class(profile)
            lane_state = lane_statuses.setdefault(
                execution_lane,
                {"status": "healthy", "failures": 0, "recovery_attempts": 0, "last_objective": "", "last_recovery_summary": ""},
            )
            lane_state["last_objective"] = item
            if execution_class != "inspect" and lane_state.get("status") == "blocked":
                overall_success = False
                if not next_action:
                    next_action = item
                reports.append(
                    {
                        "index": idx,
                        "objective": item,
                        "mode": "blocked",
                        "success": False,
                        "goal_achieved": False,
                        "summary": f"lane_blocked:{execution_lane}",
                        "task_model": profile,
                        "execution_class": execution_class,
                        "execution_lane": execution_lane,
                        "execution_mode": "lane_blocked",
                    }
                )
                idx += 1
                continue
            if execution_class != "inspect" and lane_state.get("status") == "degraded":
                recovery_budget = max(0.2, remaining_budget * 0.5)
                recovery_run = await _run_operator_lane_recovery(
                    execution_lane,
                    item,
                    profile,
                    timeout_s=recovery_budget,
                )
                for shot_path in list(recovery_run.get("screenshots") or []):
                    if shot_path:
                        artifacts.append(str(shot_path))
                recovery = await _probe_operator_lane(
                    execution_lane,
                    item,
                    profile,
                    timeout_s=max(0.1, remaining_budget - recovery_budget),
                )
                lane_state["recovery_attempts"] = int(lane_state.get("recovery_attempts", 0)) + 1
                lane_state["last_recovery_summary"] = str(recovery.get("summary") or recovery_run.get("message") or "")
                lane_recovery_attempts.append(
                    {
                        "lane": execution_lane,
                        "objective": item,
                        "self_heal_success": bool(recovery_run.get("success")),
                        "self_heal_steps": list(recovery_run.get("steps") or []),
                        "success": bool(recovery.get("success")),
                        "summary": str(recovery.get("summary") or ""),
                    }
                )
                recovery_path = str(recovery.get("path") or "").strip()
                if recovery_path:
                    artifacts.append(recovery_path)
                if bool(recovery_run.get("success")) and bool(recovery.get("success")):
                    lane_state["status"] = "healthy"
                else:
                    lane_state["status"] = "blocked"
                    overall_success = False
                    if not next_action:
                        next_action = item
                    reports.append(
                        {
                            "index": idx,
                            "objective": item,
                            "mode": "blocked",
                            "success": False,
                            "goal_achieved": False,
                            "summary": f"lane_recovery_failed:{execution_lane}",
                            "task_model": profile,
                            "execution_class": execution_class,
                            "execution_lane": execution_lane,
                            "execution_mode": "lane_recovery_blocked",
                        }
                    )
                    idx += 1
                    continue
            subtask = await _run_operator_subtask(
                item,
                pause_ms=pause_ms,
                timeout_s=remaining_budget,
                execution_mode="lane_recovered_serial" if execution_class != "inspect" and int(lane_state.get("recovery_attempts", 0)) > 0 else "serial",
            )
            success = bool(subtask.get("success")) and bool(subtask.get("goal_achieved") or subtask.get("mode") == "inspect")
            reports.append(
                {
                    "index": idx,
                    "objective": item,
                    "mode": str(subtask.get("mode") or ""),
                    "success": bool(subtask.get("success")),
                    "goal_achieved": bool(subtask.get("goal_achieved")),
                    "summary": str(subtask.get("message") or ""),
                    "task_model": subtask.get("profile"),
                    "execution_class": str(subtask.get("execution_class") or ""),
                    "execution_lane": str(subtask.get("execution_lane") or ""),
                    "execution_mode": str(subtask.get("execution_mode") or "serial"),
                }
            )
            for shot_path in list(subtask.get("artifacts") or []):
                if shot_path:
                    artifacts.append(str(shot_path))
            if success:
                lane_state["status"] = "healthy"
                completed += 1
                idx += 1
                continue

            overall_success = False
            lane_state["failures"] = int(lane_state.get("failures", 0)) + 1
            if execution_class != "inspect":
                lane_state["status"] = "degraded"
            if not next_action:
                next_action = item
            idx += 1
            continue

        summary = (
            f"Operator mission tamamlandi: {completed}/{len(subtasks)} gorev tamamlandi."
            if overall_success
            else f"Operator mission kismi kaldi: {completed}/{len(subtasks)} gorev tamamlandi."
        )
        return {
            "success": overall_success,
            "goal_achieved": overall_success,
            "message": summary,
            "summary": summary,
            "mission": mission,
            "subtasks": reports,
            "completed_subtasks": completed,
            "objective_count": len(subtasks),
            "parallelizable_groups": parallelizable_groups,
            "executed_parallel_groups": executed_parallel_groups,
            "scheduler_plan": scheduler_plan,
            "lane_statuses": lane_statuses,
            "lane_recovery_attempts": lane_recovery_attempts,
            "next_action": next_action,
            "timeout_s": mission_timeout_s,
            "artifacts": [{"path": p, "type": "image"} for p in list(dict.fromkeys(artifacts)) if p],
            "screenshots": list(dict.fromkeys(artifacts)),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _normalize_text_for_match(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    norm = unicodedata.normalize("NFKD", raw)
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", norm).strip()


def _goal_markers(goal: str) -> list[str]:
    profile = _build_operator_goal_profile(goal)
    low = str(profile.get("normalized_goal") or "")
    if not low:
        return []
    markers = [str(m).strip() for m in list(profile.get("verification_markers") or []) if str(m).strip()]
    if markers:
        return markers[:6]
    words = re.findall(r"[a-z0-9]{3,}", low)
    stop = {
        "google", "open", "ac", "ara", "search", "enter", "bas", "ve", "ile", "icin",
        "gore", "hedef", "gorev", "klavye", "mouse", "bilgisayar", "otomatik", "adim",
    }
    return [w for w in words if w not in stop][:6]


def _screen_matches_goal(goal: str, analysis: Dict[str, Any]) -> bool:
    profile = _build_operator_goal_profile(goal)
    ui_map = analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}
    frontmost_app = _normalize_text_for_match(str(ui_map.get("frontmost_app") or ""))
    normalized_target_app = _normalize_text_for_match(str(profile.get("target_app") or ""))
    if (
        normalized_target_app
        and frontmost_app == normalized_target_app
        and bool(profile.get("wants_open"))
        and not any(
            (
                bool(profile.get("wants_search")),
                bool(str(profile.get("typed_text") or "").strip()),
                bool(str(profile.get("target_url") or "").strip()),
                bool(profile.get("wants_click")),
                bool(profile.get("wants_save")),
                bool(profile.get("wants_submit")),
            )
        )
    ):
        return True
    markers = _goal_markers(goal)
    if not markers:
        return False
    hay = " ".join(
        [
            _normalize_text_for_match(str(analysis.get("summary") or "")),
            _normalize_text_for_match(str(analysis.get("ocr") or "")),
            _normalize_text_for_match(json.dumps(analysis.get("objects", []), ensure_ascii=False)),
            _normalize_text_for_match(json.dumps(analysis.get("ui_map", {}), ensure_ascii=False)),
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
    profile = _build_operator_goal_profile(goal)
    if bool(profile.get("read_only")):
        return []
    ui_map = analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}
    frontmost_app = _normalize_text_for_match(str(ui_map.get("frontmost_app") or ""))
    target_app = str(profile.get("target_app") or "")
    normalized_target_app = _normalize_text_for_match(target_app)
    launch_wait_s = max(0.2, min(2.0, float(profile.get("launch_wait_s", 0.7) or 0.7)))
    query = str(profile.get("search_query") or "").strip() or " ".join(_goal_markers(goal)) or str(goal or "").strip()
    steps: list[dict[str, Any]] = []

    if target_app and normalized_target_app and normalized_target_app != frontmost_app:
        if bool(profile.get("wants_close")):
            steps.append({"action": "close_app", "params": {"app_name": target_app}})
        else:
            steps.extend(
                [
                    {"action": "open_app", "params": {"app_name": target_app}},
                    {"action": "wait", "params": {"seconds": launch_wait_s}},
                ]
            )

    coordinate_hints = list(ui_map.get("coordinate_hints") or [])
    if bool(profile.get("wants_click")) and coordinate_hints:
        point = coordinate_hints[0]
        if isinstance(point, dict) and "x" in point and "y" in point:
            steps.append({"action": "mouse_click", "params": {"x": int(point["x"]), "y": int(point["y"])}})

    if str(profile.get("target_url") or "").strip():
        steps.append(
            {
                "action": "open_url",
                "params": {"url": str(profile.get("target_url") or "").strip(), "browser": str(profile.get("browser_app") or "Safari")},
            }
        )
    elif bool(profile.get("wants_search")) and query:
        steps.extend(
            [
                {"action": "key_combo", "params": {"combo": "cmd+l"}},
                {"action": "type_text", "params": {"text": query, "press_enter": True}},
                {"action": "wait", "params": {"seconds": max(0.9, launch_wait_s)}},
            ]
        )
    elif str(profile.get("typed_text") or "").strip():
        steps.append(
            {
                "action": "type_text",
                "params": {"text": str(profile.get("typed_text") or "").strip(), "press_enter": bool(profile.get("wants_submit"))},
            }
        )

    if bool(profile.get("wants_save")):
        steps.extend(
            [
                {"action": "key_combo", "params": {"combo": "cmd+s"}},
                {"action": "wait", "params": {"seconds": 0.5}},
            ]
        )
    return steps[:6]


async def _get_frontmost_app_name() -> str:
    try:
        script = (
            'tell application "System Events" to get name of first application process '
            "whose frontmost is true"
        )
        code, out, _ = await _run_osascript(script)
        if code == 0 and str(out).strip():
            return str(out).strip()
    except Exception:
        pass
    return ""


async def _collect_operator_status() -> dict[str, Any]:
    frontmost = await _get_frontmost_app_name()
    apps_res = await get_running_apps()
    apps: list[str] = []
    if isinstance(apps_res, dict) and apps_res.get("success"):
        apps = [str(app).strip() for app in list(apps_res.get("apps") or []) if str(app).strip()]
    preview = ", ".join(apps[:5]) if apps else ""
    extra_count = max(0, len(apps) - 5)
    return {
        "frontmost_app": frontmost,
        "running_apps": apps,
        "running_apps_count": len(apps),
        "running_apps_preview": preview,
        "running_apps_extra_count": extra_count,
    }


def _extract_coordinate_candidates(text: str) -> list[dict[str, int]]:
    src = str(text or "")
    if not src.strip():
        return []
    coords: list[dict[str, int]] = []
    patterns = [
        r"\(\s*(\d{1,4})\s*,\s*(\d{1,4})\s*\)",
        r"\bx\s*[:=]\s*(\d{1,4})\D+y\s*[:=]\s*(\d{1,4})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, src, flags=re.IGNORECASE):
            try:
                x = int(match.group(1))
                y = int(match.group(2))
            except Exception:
                continue
            if 0 <= x <= 10000 and 0 <= y <= 10000:
                coords.append({"x": x, "y": y})
    out: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for item in coords:
        key = (int(item["x"]), int(item["y"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:12]


def _append_ui_element(elements: list[dict[str, Any]], seen: set[tuple[str, str]], *, label: str, kind: str, confidence: float, x: Optional[int] = None, y: Optional[int] = None) -> None:
    clean_label = str(label or "").strip()
    if not clean_label:
        return
    key = (_normalize_text_for_match(clean_label), str(kind or "").strip().lower())
    if not key[0] or key in seen:
        return
    seen.add(key)
    item: dict[str, Any] = {
        "label": clean_label[:120],
        "kind": str(kind or "unknown").strip().lower() or "unknown",
        "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
    }
    if x is not None and y is not None:
        item["x"] = int(x)
        item["y"] = int(y)
    elements.append(item)


async def _build_ui_map_from_analysis(
    *,
    summary: str,
    ocr: str,
    objects: Any,
    status: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    op_status = status if isinstance(status, dict) else await _collect_operator_status()
    frontmost = str(op_status.get("frontmost_app") or "").strip()
    running_apps = [str(app).strip() for app in list(op_status.get("running_apps") or []) if str(app).strip()]

    text_blob = "\n".join([str(summary or ""), str(ocr or "")])
    coords = _extract_coordinate_candidates(text_blob)
    elements: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if frontmost:
        _append_ui_element(elements, seen, label=frontmost, kind="frontmost_app", confidence=0.99)
    for app in running_apps[:20]:
        _append_ui_element(elements, seen, label=app, kind="app", confidence=0.8)

    if isinstance(objects, list):
        for obj in objects[:20]:
            if isinstance(obj, dict):
                name = str(obj.get("name") or obj.get("label") or "").strip()
                kind = str(obj.get("kind") or obj.get("type") or "object").strip().lower()
                x = obj.get("x")
                y = obj.get("y")
                xi = int(x) if isinstance(x, (int, float)) else None
                yi = int(y) if isinstance(y, (int, float)) else None
                _append_ui_element(elements, seen, label=name, kind=kind, confidence=0.7, x=xi, y=yi)
            else:
                _append_ui_element(elements, seen, label=str(obj), kind="object", confidence=0.6)

    for match in re.findall(r"[\"']([^\"']{2,60})[\"']", text_blob):
        _append_ui_element(elements, seen, label=match, kind="text", confidence=0.55)

    for point in coords:
        _append_ui_element(
            elements,
            seen,
            label=f"point_{point['x']}_{point['y']}",
            kind="coordinate_hint",
            confidence=0.5,
            x=point["x"],
            y=point["y"],
        )

    return {
        "frontmost_app": frontmost,
        "running_apps": running_apps,
        "elements": elements[:30],
        "coordinate_hints": coords,
        "coordinates_detected": bool(coords),
        "source": "vision_operator_hybrid",
    }


async def _build_screen_analysis_fallback(shot_path: str, error_text: str = "") -> dict[str, Any]:
    status = await _collect_operator_status()
    frontmost = str(status.get("frontmost_app") or "").strip()
    apps = list(status.get("running_apps") or [])

    summary_parts = []
    if frontmost:
        summary_parts.append(f"On planda {frontmost} acik gorunuyor.")
    if apps:
        preview = ", ".join(apps[:5])
        extra = f" ve +{len(apps) - 5}" if len(apps) > 5 else ""
        summary_parts.append(f"Calisan uygulamalar: {preview}{extra}.")
    if not summary_parts:
        summary_parts.append("Ekran goruntusu alindi fakat gorsel analiz servisi su an yanit vermedi.")

    warning = str(error_text or "").strip()
    if warning:
        summary_parts.append(f"Vision fallback kullanildi: {warning}")

    summary_text = " ".join(summary_parts).strip()
    ui_map = await _build_ui_map_from_analysis(
        summary=summary_text,
        ocr="",
        objects=[{"name": frontmost, "kind": "frontmost_app"}] if frontmost else [],
        status=status,
    )

    return {
        "success": True,
        "path": shot_path,
        "summary": summary_text,
        "ocr": "",
        "objects": [{"name": frontmost, "kind": "frontmost_app"}] if frontmost else [],
        "risks": ["vision_unavailable"],
        "provider": "fallback/operator_state",
        "warning": warning,
        "analysis_mode": "fallback",
        "status_report": status,
        "ui_map": ui_map,
    }


_VISION_LOW_QUALITY_MARKERS = {
    "kac adet hayvan",
    "kaç adet hayvan",
    "peri",
    "hayvan",
    "gunesle gece",
    "güneşle gece",
    "the gorsel",
    "the görsel",
    "onermelim",
    "önermelim",
}


def _is_status_like_prompt(text: str) -> bool:
    low = _normalize_text_for_match(text)
    markers = (
        "durum nedir",
        "ekranda ne var",
        "ekrana bak",
        "ekrani oku",
        "ekrani oku",
        "status",
        "screen",
    )
    return any(m in low for m in markers)


def _summary_mentions_ui_or_apps(summary: str, frontmost: str, apps: list[str]) -> bool:
    low = _normalize_text_for_match(summary)
    if not low:
        return False
    front = _normalize_text_for_match(frontmost)
    if front and front in low:
        return True
    for app in apps[:12]:
        app_norm = _normalize_text_for_match(app)
        if len(app_norm) >= 3 and app_norm in low:
            return True
    ui_markers = (
        "uygulama",
        "pencere",
        "sekme",
        "tarayici",
        "browser",
        "terminal",
        "editor",
        "chrome",
        "safari",
        "finder",
        "cursor",
        "codex",
    )
    return any(m in low for m in ui_markers)


async def _apply_vision_quality_gate(
    analysis: Dict[str, Any],
    shot_path: str,
    prompt_text: str,
) -> Dict[str, Any]:
    summary = str(analysis.get("analysis") or "").strip()
    summary_norm = _normalize_text_for_match(summary)
    if not summary:
        return await _build_screen_analysis_fallback(shot_path, "vision_quality_gate:empty_summary")

    if any(marker in summary_norm for marker in _VISION_LOW_QUALITY_MARKERS):
        return await _build_screen_analysis_fallback(shot_path, "vision_quality_gate:hallucination_marker")

    if len(summary.split()) < 6:
        return await _build_screen_analysis_fallback(shot_path, "vision_quality_gate:too_short")

    if _is_status_like_prompt(prompt_text):
        status = await _collect_operator_status()
        frontmost = str(status.get("frontmost_app") or "").strip()
        apps = list(status.get("running_apps") or [])
        if not _summary_mentions_ui_or_apps(summary, frontmost, apps):
            return await _build_screen_analysis_fallback(shot_path, "vision_quality_gate:no_ui_signal")

    analysis_copy = dict(analysis)
    analysis_copy["analysis"] = " ".join(summary.split())[:700]
    return analysis_copy

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
        started_at = time.monotonic()
        step_timeout_s = _operator_step_timeout_s()
        mission_timeout_s = _operator_mission_timeout_s()
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
        recent_signatures: list[str] = []
        repeated_repairs = 0

        while pending_steps:
            elapsed = time.monotonic() - started_at
            if elapsed >= mission_timeout_s:
                return {
                    "success": False,
                    "error": f"operator_mission_timeout:{mission_timeout_s:.1f}s",
                    "error_code": "operator_mission_timeout",
                    "steps": results,
                    "screenshots": screenshots,
                }
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
            signature = _step_signature(step)
            recent_signatures.append(signature)
            recent_signatures = recent_signatures[-6:]
            if signature and recent_signatures.count(signature) >= 4:
                return {
                    "success": False,
                    "error": f"operator_deadlock_detected:{action}",
                    "error_code": "operator_deadlock_detected",
                    "steps": results,
                    "screenshots": screenshots,
                }

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

            res = await _await_operator_budget(_exec_step(), timeout_s=step_timeout_s, label="operator_step")
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
                res = await _await_operator_budget(_exec_step(), timeout_s=step_timeout_s, label="operator_step")

            results.append({"step": idx, "action": action, "success": bool(res.get("success")), "result": res})
            if not bool(res.get("success")):
                return {"success": False, "error": f"Adım {idx} başarısız: {res.get('error', 'unknown')}", "steps": results, "screenshots": screenshots}

            if screenshot_after_each:
                shot = await take_screenshot(filename=f"computer_use_step_{idx}_{int(time.time())}.png")
                if shot.get("success") and shot.get("path"):
                    screenshots.append(str(shot.get("path")))

            if vision_feedback and str(goal or "").strip() and _should_probe_vision(action, generated_from_goal):
                analysis = await _await_operator_budget(
                    analyze_screen(prompt=f"Hedef doğrulaması: {goal}"),
                    timeout_s=step_timeout_s,
                    label="operator_verify",
                )
                ui_map = analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}
                frontmost_app = str(ui_map.get("frontmost_app") or "").strip()
                brief = {
                    "step": idx,
                    "action": action,
                    "success": bool(analysis.get("success")),
                    "summary": str(analysis.get("summary") or "")[:400],
                    "ocr": str(analysis.get("ocr") or "")[:400],
                    "provider": str(analysis.get("provider") or ""),
                    "frontmost_app": frontmost_app,
                    "coordinates_detected": bool(ui_map.get("coordinates_detected")),
                }
                vision_observations.append(brief)
                if bool(analysis.get("success")) and _screen_matches_goal(goal, analysis):
                    goal_achieved = True
                    break
                if feedback_used < feedback_budget:
                    repair_steps = _build_goal_repair_steps(goal, analysis)
                    if repair_steps:
                        repair_signatures = [_step_signature(item) for item in repair_steps if _step_signature(item)]
                        if repair_signatures and all(sig in recent_signatures for sig in repair_signatures[:2]):
                            repeated_repairs += 1
                        else:
                            repeated_repairs = 0
                        if repeated_repairs >= 2:
                            return {
                                "success": False,
                                "error": "operator_repair_deadlock",
                                "error_code": "operator_repair_deadlock",
                                "steps": results,
                                "screenshots": screenshots,
                                "vision_observations": vision_observations,
                            }
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
                analysis = await _await_operator_budget(
                    analyze_screen(prompt=f"Hedef doğrulaması: {goal}"),
                    timeout_s=step_timeout_s,
                    label="operator_verify",
                )
                vision_observations.append(
                    {
                        "success": bool(analysis.get("success")),
                        "summary": str(analysis.get("summary") or "")[:400],
                        "ocr": str(analysis.get("ocr") or "")[:400],
                        "provider": str(analysis.get("provider") or ""),
                        "frontmost_app": str(
                            ((analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}) or {}).get("frontmost_app")
                            or ""
                        ).strip(),
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
                        await _await_operator_budget(
                            key_combo(combo=str(r_params.get("combo") or "").strip()),
                            timeout_s=step_timeout_s,
                            label="operator_step",
                        )
                    elif r_action == "type_text":
                        await _await_operator_budget(
                            type_text(
                                text=str(r_params.get("text") or "").strip(),
                                press_enter=bool(r_params.get("press_enter", False)),
                            ),
                            timeout_s=step_timeout_s,
                            label="operator_step",
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
            "operator_budget": {
                "step_timeout_s": step_timeout_s,
                "mission_timeout_s": mission_timeout_s,
                "elapsed_s": round(time.monotonic() - started_at, 3),
            },
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
        analysis = await _analyze_image_with_timeout(str(shot_path or ""), prompt)
        if not analysis.get("success"):
            return await _build_screen_analysis_fallback(
                str(shot_path or ""),
                analysis.get("error", ""),
            )
        analysis = await _apply_vision_quality_gate(
            analysis,
            str(shot_path or ""),
            prompt,
        )
        normalized = _normalize_screen_analysis_payload(analysis, str(shot_path or ""))
        if not isinstance(normalized.get("ui_map"), dict):
            status = normalized.get("status_report")
            normalized["ui_map"] = await _build_ui_map_from_analysis(
                summary=str(normalized.get("summary") or ""),
                ocr=str(normalized.get("ocr") or ""),
                objects=normalized.get("objects", []),
                status=status if isinstance(status, dict) else None,
            )
        return normalized
    except Exception as e:
        return {"success": False, "error": str(e)}


_ORIGINAL_ANALYZE_SCREEN = analyze_screen
_ORIGINAL_COMPUTER_USE = computer_use


def _compat_ui_state_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    ui_map = analysis.get("ui_map") if isinstance(analysis.get("ui_map"), dict) else {}
    elements = [dict(item) for item in list(ui_map.get("elements") or []) if isinstance(item, dict)]
    source_counts = dict(ui_map.get("source_counts") or {}) if isinstance(ui_map.get("source_counts"), dict) else {}
    if not source_counts and elements:
        source_counts["compat_analysis"] = len(elements)
    summary = str(analysis.get("summary") or ui_map.get("summary") or "").strip()
    return {
        "frontmost_app": str(ui_map.get("frontmost_app") or "").strip(),
        "active_window": {
            "title": str(ui_map.get("window_title") or ui_map.get("active_window") or "").strip(),
            "bounds": dict(ui_map.get("bounds") or {}) if isinstance(ui_map.get("bounds"), dict) else {},
        },
        "elements": elements,
        "clickable_targets": [dict(item) for item in elements if any(k in str(item.get("kind") or item.get("role") or "").lower() for k in ("button", "link", "tab", "field", "input"))],
        "text_fields": [dict(item) for item in elements if any(k in str(item.get("kind") or item.get("role") or "").lower() for k in ("field", "input", "text"))],
        "summary": summary,
        "fallback_order": ["compat_analysis_bridge"],
        "source_counts": source_counts,
        "confidence": float(ui_map.get("confidence") or (0.8 if analysis.get("success") else 0.0)),
    }


def _compat_observation_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    payload = dict(analysis or {})
    ui_state = _compat_ui_state_from_analysis(payload)
    screenshot_path = str(payload.get("path") or "").strip()
    summary = str(payload.get("summary") or ui_state.get("summary") or payload.get("message") or "").strip()
    vision_payload = {
        "provider": str(payload.get("provider") or "legacy/analyze_screen").strip(),
        "summary": summary,
    }
    warning = str(payload.get("warning") or payload.get("error") or "").strip()
    if warning:
        vision_payload["warning"] = warning
    return {
        "success": bool(payload.get("success")),
        "summary": summary,
        "screenshot": {"path": screenshot_path} if screenshot_path else {},
        "window_metadata": {
            "frontmost_app": str(ui_state.get("frontmost_app") or "").strip(),
            "window_title": str((ui_state.get("active_window") or {}).get("title") or "").strip(),
            "bounds": dict((ui_state.get("active_window") or {}).get("bounds") or {}),
        },
        "accessibility": {"elements": list(ui_state.get("elements") or [])},
        "ocr": {"text": str(payload.get("ocr") or "").strip()},
        "vision": vision_payload,
        "ui_state": ui_state,
    }


def _compat_action_logs_from_computer_use(control_result: dict[str, Any]) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for item in list(control_result.get("steps") or []):
        if not isinstance(item, dict):
            continue
        step_number = int(item.get("step") or (len(logs) + 1))
        action_name = str(item.get("action") or "").strip().lower()
        result_payload = item.get("result") if isinstance(item.get("result"), dict) else {}
        log_entry = {
            "step": step_number,
            "attempt": 1,
            "planned_action": {"kind": action_name or "unknown"},
            "execution_result": dict(result_payload),
        }
        verification = {
            "ok": bool(result_payload.get("success")),
            "failed_codes": [] if bool(result_payload.get("success")) else [str(result_payload.get("error_code") or "legacy_control_failed").strip()],
        }
        log_entry["verification"] = verification
        logs.append(log_entry)
    return logs


async def _run_screen_operator_legacy_bridge(
    *,
    goal: str,
    mode: str,
    final_screenshot: bool,
    max_actions: int,
) -> dict[str, Any] | None:
    analyze_patched = analyze_screen is not _ORIGINAL_ANALYZE_SCREEN
    computer_patched = computer_use is not _ORIGINAL_COMPUTER_USE
    if not (analyze_patched or computer_patched):
        return None

    started_at = time.monotonic()
    prompt = goal or "Ekranda ne var? Özetle."
    before_analysis = await analyze_screen(prompt=prompt)
    before_observation = _compat_observation_from_analysis(before_analysis if isinstance(before_analysis, dict) else {})
    before_path = str(((before_observation.get("screenshot") if isinstance(before_observation.get("screenshot"), dict) else {}) or {}).get("path") or "").strip()
    screenshots = [before_path] if before_path else []
    artifacts = [{"path": before_path, "type": "image"}] if before_path else []
    ui_state = dict(before_observation.get("ui_state") or {})
    summary = str(before_observation.get("summary") or "").strip()
    verifier_outcomes: list[dict[str, Any]] = []
    action_logs: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []

    if mode == "inspect":
        return {
            "success": bool(before_analysis.get("success")),
            "status": "success" if bool(before_analysis.get("success")) else "failed",
            "mode": mode,
            "goal_achieved": bool(before_analysis.get("success")),
            "message": summary or "Screen inspected.",
            "summary": summary or "Screen inspected.",
            "ui_state": ui_state,
            "plan": plan,
            "initial_observation": before_observation,
            "final_observation": before_observation,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": 0, "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": screenshots,
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {"current_step": 0, "attempts": 0, "ui_state": ui_state, "last_target_cache": {}, "verifier_outcomes": verifier_outcomes},
        }

    if bool(before_analysis.get("success")) and _screen_matches_goal(goal, before_analysis):
        verification = {"ok": True, "failed_codes": [], "source": "legacy_analysis_bridge"}
        verifier_outcomes.append(verification)
        return {
            "success": True,
            "status": "success",
            "mode": mode,
            "goal_achieved": True,
            "message": summary or "Goal already visible.",
            "summary": summary or "Goal already visible.",
            "ui_state": ui_state,
            "plan": plan,
            "initial_observation": before_observation,
            "final_observation": before_observation,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": 0, "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": screenshots,
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {"current_step": 0, "attempts": 0, "ui_state": ui_state, "last_target_cache": {}, "verifier_outcomes": verifier_outcomes},
        }

    if not computer_patched:
        return {
            "success": False,
            "status": "failed",
            "mode": mode,
            "goal_achieved": False,
            "error": "legacy_control_hook_requires_computer_use_patch",
            "error_code": "legacy_control_hook_requires_computer_use_patch",
            "message": summary or "Legacy bridge cannot drive control without a patched computer_use hook.",
            "summary": summary,
            "ui_state": ui_state,
            "plan": plan,
            "initial_observation": before_observation,
            "final_observation": before_observation,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": 0, "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": screenshots,
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {"current_step": 0, "attempts": 0, "ui_state": ui_state, "last_target_cache": {}, "verifier_outcomes": verifier_outcomes},
        }

    control_result = await computer_use(
        steps=None,
        goal=goal,
        auto_plan=True,
        final_screenshot=bool(final_screenshot),
        vision_feedback=True,
        max_feedback_loops=max(0, int(max_actions or 0)),
    )
    action_logs = _compat_action_logs_from_computer_use(control_result if isinstance(control_result, dict) else {})
    after_analysis = before_analysis if isinstance(before_analysis, dict) else {}
    if analyze_patched:
        after_analysis = await analyze_screen(prompt=f"Hedef doğrulaması: {goal}")
    after_observation = _compat_observation_from_analysis(after_analysis if isinstance(after_analysis, dict) else {})
    after_path = str(((after_observation.get("screenshot") if isinstance(after_observation.get("screenshot"), dict) else {}) or {}).get("path") or "").strip()
    if after_path:
        screenshots.append(after_path)
        artifacts.append({"path": after_path, "type": "image"})
    goal_achieved = bool(after_analysis.get("success")) and _screen_matches_goal(goal, after_analysis)
    if not goal_achieved:
        goal_achieved = bool(control_result.get("goal_achieved") or (control_result.get("success") and not str(control_result.get("error") or "").strip()))
    verification = {
        "ok": bool(goal_achieved),
        "failed_codes": [] if bool(goal_achieved) else [str(control_result.get("error_code") or "legacy_control_failed").strip()],
        "source": "legacy_computer_use_bridge",
    }
    verifier_outcomes.append(verification)
    success = bool(control_result.get("success")) and bool(goal_achieved)
    final_ui_state = dict(after_observation.get("ui_state") or ui_state)
    final_summary = str(after_observation.get("summary") or summary or control_result.get("message") or "").strip()
    return {
        "success": success,
        "status": "success" if success else "failed",
        "mode": mode,
        "goal_achieved": bool(goal_achieved),
        "error": "" if success else str(control_result.get("error") or "legacy_control_failed").strip(),
        "error_code": "" if success else str(control_result.get("error_code") or "legacy_control_failed").strip(),
        "message": final_summary or str(control_result.get("message") or "Legacy control bridge completed.").strip(),
        "summary": final_summary or str(control_result.get("message") or "").strip(),
        "ui_state": final_ui_state,
        "plan": plan,
        "initial_observation": before_observation,
        "final_observation": after_observation,
        "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": 0, "elapsed_s": round(time.monotonic() - started_at, 3)},
        "screenshots": list(dict.fromkeys([path for path in screenshots if path])),
        "artifacts": [item for item in artifacts if str(item.get("path") or "").strip()],
        "action_logs": action_logs,
        "verifier_outcomes": verifier_outcomes,
        "task_state": {
            "current_step": len(action_logs),
            "attempts": len(action_logs),
            "ui_state": final_ui_state,
            "last_target_cache": {},
            "verifier_outcomes": verifier_outcomes,
        },
    }


@tool("screen_workflow", "Read the screen, optionally control the computer, and verify the result.")
async def screen_workflow(
    instruction: str = "",
    mode: str = "inspect",
    region: Optional[Dict[str, Any]] = None,
    action_goal: str = "",
    final_screenshot: bool = True,
    include_analysis: bool = True,
) -> dict[str, Any]:
    """
    Unified operator workflow for screen-centric tasks.

    Modes:
    - inspect: take/capture screen and analyze it
    - control: run computer_use against action_goal or instruction
    - inspect_and_control: inspect first, then control, then verify again
    """
    try:
        from core.runtime.hosts import get_desktop_host

        normalized_mode = str(mode or "inspect").strip().lower()
        if normalized_mode not in {"inspect", "control", "inspect_and_control"}:
            normalized_mode = "inspect"
        goal = str(action_goal or instruction or "").strip()
        runtime_result = await _run_screen_operator_legacy_bridge(
            goal=goal,
            mode=normalized_mode,
            final_screenshot=bool(final_screenshot),
            max_actions=1,
        )
        if runtime_result is None:
            runtime_result = await get_desktop_host().run_screen_operator(
                instruction=goal,
                mode=normalized_mode,
                region=region if isinstance(region, dict) else None,
                final_screenshot=bool(final_screenshot),
            )

        def _to_observation(stage: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(payload, dict):
                return None
            screenshot = payload.get("screenshot") if isinstance(payload.get("screenshot"), dict) else {}
            vision = payload.get("vision") if isinstance(payload.get("vision"), dict) else {}
            ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
            ui_state = payload.get("ui_state") if isinstance(payload.get("ui_state"), dict) else {}
            return {
                "stage": stage,
                "success": bool(payload.get("success", True)),
                "summary": str(payload.get("summary") or ui_state.get("summary") or "").strip(),
                "provider": str(vision.get("provider") or vision.get("source") or ""),
                "warning": str(vision.get("warning") or vision.get("error") or ocr.get("error") or "").strip(),
                "ui_map": ui_state,
                "path": str(screenshot.get("path") or "").strip(),
                "ocr": str(ocr.get("text") or "").strip(),
            }

        observations: list[dict[str, Any]] = []
        if include_analysis:
            before = _to_observation("before", runtime_result.get("initial_observation"))
            after = _to_observation("after", runtime_result.get("final_observation"))
            if before:
                observations.append(before)
            if (
                after
                and normalized_mode in {"control", "inspect_and_control"}
                and after.get("path") != (before or {}).get("path")
            ):
                observations.append(after)

        control_result = {}
        if normalized_mode in {"control", "inspect_and_control"}:
            control_result = {
                "message": str(runtime_result.get("message") or "").strip(),
                "goal_achieved": bool(runtime_result.get("goal_achieved")),
                "action_logs": list(runtime_result.get("action_logs") or []),
                "verifier_outcomes": list(runtime_result.get("verifier_outcomes") or []),
                "task_state": dict(runtime_result.get("task_state") or {}),
            }

        response = {
            "success": bool(runtime_result.get("success")),
            "mode": normalized_mode,
            "instruction": instruction,
            "message": str(runtime_result.get("message") or runtime_result.get("summary") or "").strip(),
            "summary": str(runtime_result.get("summary") or runtime_result.get("message") or "").strip(),
            "observations": observations,
            "control": control_result,
            "artifacts": sorted(
                list(runtime_result.get("artifacts") or []),
                key=lambda item: 0 if str((item or {}).get("type") or "") == "image" else 1,
            ),
            "screenshots": list(runtime_result.get("screenshots") or []),
            "ui_state": dict(runtime_result.get("ui_state") or {}),
            "task_state": dict(runtime_result.get("task_state") or {}),
            "verifier_outcomes": list(runtime_result.get("verifier_outcomes") or []),
        }
        if not response["success"]:
            response["error"] = str(runtime_result.get("error") or "screen_operator_failed")
            if str(runtime_result.get("error_code") or "").strip():
                response["error_code"] = str(runtime_result.get("error_code") or "").strip()
        return response
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("vision_operator_loop", "Run an iterative read-plan-act-verify loop for screen objectives.")
async def vision_operator_loop(
    objective: str,
    max_iterations: int = 2,
    pause_ms: int = 250,
    include_ui_map: bool = True,
) -> dict[str, Any]:
    try:
        from core.runtime.hosts import get_desktop_host

        goal = str(objective or "").strip()
        if not goal:
            return {"success": False, "error": "objective gerekli."}

        task_model = _build_operator_goal_profile(goal)
        runtime_mode = "inspect" if bool(task_model.get("read_only")) else "control"
        runtime_result = await _run_screen_operator_legacy_bridge(
            goal=goal,
            mode=runtime_mode,
            final_screenshot=True,
            max_actions=max_iterations,
        )
        if runtime_result is None:
            runtime_result = await get_desktop_host().run_screen_operator(
                instruction=goal,
                mode=runtime_mode,
                max_actions=max_iterations,
                final_screenshot=True,
            )

        def _compact(observation: dict[str, Any] | None) -> dict[str, Any]:
            payload = observation if isinstance(observation, dict) else {}
            ui_state = payload.get("ui_state") if isinstance(payload.get("ui_state"), dict) else {}
            vision = payload.get("vision") if isinstance(payload.get("vision"), dict) else {}
            compact = {
                "success": bool(payload.get("success", True)),
                "provider": str(vision.get("provider") or ""),
                "summary": str(payload.get("summary") or ui_state.get("summary") or "")[:450],
                "warning": str(vision.get("warning") or vision.get("error") or "").strip()[:220],
                "frontmost_app": str(ui_state.get("frontmost_app") or "").strip(),
                "coordinates_detected": bool(ui_state.get("source_counts", {}).get("vision") or ui_state.get("source_counts", {}).get("ocr")),
            }
            if include_ui_map:
                compact["ui_map"] = ui_state
            return compact

        reports: list[dict[str, Any]] = []
        initial_observation = runtime_result.get("initial_observation") if isinstance(runtime_result.get("initial_observation"), dict) else {}
        final_observation = runtime_result.get("final_observation") if isinstance(runtime_result.get("final_observation"), dict) else {}
        action_logs = [item for item in list(runtime_result.get("action_logs") or []) if isinstance(item, dict)]

        if runtime_mode == "inspect":
            reports.append({"iteration": 1, "before": _compact(initial_observation), "result": "inspection_only"})
        elif action_logs:
            for idx, log in enumerate(action_logs, start=1):
                verification = log.get("verification") if isinstance(log.get("verification"), dict) else {}
                execution_result = log.get("execution_result") if isinstance(log.get("execution_result"), dict) else {}
                report = {
                    "iteration": idx,
                    "action": {
                        "success": bool(execution_result.get("success")),
                        "goal_achieved": bool(verification.get("ok")),
                        "error": str(execution_result.get("error") or "")[:220],
                    },
                    "verification": verification,
                    "result": "goal_achieved" if bool(verification.get("ok")) and idx == len(action_logs) else ("continue" if bool(execution_result.get("success")) else "failed"),
                }
                if idx == 1:
                    report["before"] = _compact(initial_observation)
                if idx == len(action_logs):
                    report["after"] = _compact(final_observation)
                reports.append(report)
        else:
            reports.append({"iteration": 1, "before": _compact(initial_observation), "result": "goal_already_visible" if runtime_result.get("goal_achieved") else "continue"})

        response = {
            "success": bool(runtime_result.get("success")),
            "goal": goal,
            "goal_achieved": bool(runtime_result.get("goal_achieved")),
            "message": str(runtime_result.get("message") or runtime_result.get("summary") or "").strip(),
            "iterations": reports,
            "plan": list(runtime_result.get("plan") or []),
            "task_model": task_model,
            "operator_budget": dict(runtime_result.get("operator_budget") or {}),
            "artifacts": list(runtime_result.get("artifacts") or []),
            "screenshots": list(runtime_result.get("screenshots") or []),
            "ui_state": dict(runtime_result.get("ui_state") or {}),
            "task_state": dict(runtime_result.get("task_state") or {}),
        }
        if not response["success"]:
            response["error"] = str(runtime_result.get("error") or "screen_operator_failed")
            if str(runtime_result.get("error_code") or "").strip():
                response["error_code"] = str(runtime_result.get("error_code") or "").strip()
        return response
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("desktop_operator_state", "Inspect current DesktopHost live operator state.")
async def desktop_operator_state() -> dict[str, Any]:
    try:
        from core.runtime.hosts import get_desktop_host

        state = await get_desktop_host().get_live_state()
        return {
            "success": True,
            "state": state,
            "frontmost_app": str(state.get("frontmost_app") or "").strip(),
            "active_window": dict(state.get("active_window") or {}),
            "last_screenshot": str(state.get("last_screenshot") or "").strip(),
            "target_cache_size": len(dict(state.get("target_cache") or {})),
            "recent_action_log_count": len(list(state.get("recent_action_logs") or [])),
            "verifier_outcome_count": len(list(state.get("verifier_outcomes") or [])),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool("reset_desktop_operator_state", "Clear current DesktopHost live operator state.")
async def reset_desktop_operator_state() -> dict[str, Any]:
    try:
        from core.runtime.hosts import get_desktop_host

        state = await get_desktop_host().clear_live_state()
        return {"success": True, "state": state}
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
