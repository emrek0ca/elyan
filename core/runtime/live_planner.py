from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlparse

from core.contracts.failure_taxonomy import FailureCode

from .task_sessions import OperatorTaskRuntime


_BROWSER_ALIASES = {
    "safari": "Safari",
    "tarayıcı": "Safari",
    "tarayici": "Safari",
    "browser": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "krom": "Google Chrome",
    "arc": "Arc",
    "firefox": "Firefox",
}
_APP_ALIASES = {
    **_BROWSER_ALIASES,
    "finder": "Finder",
    "cursor": "Cursor",
    "terminal": "Terminal",
}
_KNOWN_PAGE_URLS = {
    "upload sayfası": "https://upload.local",
    "upload sayfasi": "https://upload.local",
    "upload page": "https://upload.local",
    "giriş sayfası": "https://login.local",
    "giris sayfasi": "https://login.local",
    "login page": "https://login.local",
    "search sayfası": "https://search.local",
    "search page": "https://search.local",
}
_SELECTOR_MAP = {
    "search": "#q",
    "search field": "#q",
    "arama": "#q",
    "login": "#login",
    "giriş": "#login",
    "giris": "#login",
    "email": "#email",
    "e-posta": "#email",
    "eposta": "#email",
    "password": "#password",
    "şifre": "#password",
    "sifre": "#password",
    "upload": "#upload",
    "continue": "#continue",
    "devam": "#continue",
    "next": "#next",
    "ileri": "#next",
    "submit": "#submit",
    "save": "#save",
    "open": "#open",
}
_GENERIC_BUTTONS = {
    "continue": "Continue",
    "devam": "Continue",
    "submit": "Submit",
    "save": "Save",
    "next": "Next",
    "open": "Open",
    "search": "Search",
    "login": "Login",
    "giriş yap": "Login",
    "giris yap": "Login",
}

_FIELD_VALUE_PATTERNS = [
    (r"(?:email|e-posta|eposta)[^\"'\n]{0,24}[\"']([^\"']+)[\"']", "#email", "Email field"),
    (r"(?:şifre|sifre|password)[^\"'\n]{0,24}[\"']([^\"']+)[\"']", "#password", "Password field"),
    (r"(?:arama kutusu|arama alanı|arama alani|search field|search box)[^\"'\n]{0,24}[\"']([^\"']+)[\"']", "#q", "Search field"),
]
_BUTTON_SEQUENCE_PATTERNS = [
    (r"(?:continue|devam)(?:\s+buton(?:una|u)?)?", "Continue", "#continue"),
    (r"(?:next|ileri)(?:\s+buton(?:una|u)?)?", "Next", "#next"),
    (r"(?:save|kaydet)(?:\s+buton(?:una|u)?)?", "Save", "#save"),
    (r"(?:giriş yap|giris yap|login(?:\s+button|\s+yap)?)", "Login", "#login"),
]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _sanitize_request_for_planning(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*@[\w_]+\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*/(?:run|operator|operate|elyan)\b\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:telegram|tg)\s*:\s*", "", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def _slugify(value: str) -> str:
    parts = [item for item in "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).split("-") if item]
    return "-".join(parts) or "operator-task"


def _extract_url(text: str) -> str:
    raw = str(text or "")
    for match in re.finditer(r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9.-]+\.(?:com|org|net|io|ai|co|tr|local)(?:/[^\s]*)?)", raw, re.IGNORECASE):
        if match.start() > 0 and raw[match.start() - 1] == "@":
            continue
        url = str(match.group(1) or "").strip().rstrip(".,)")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            return url
    return ""


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    raw = str(text or "")
    for match in re.finditer(r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9.-]+\.(?:com|org|net|io|ai|co|tr|local)(?:/[^\s]*)?)", raw, re.IGNORECASE):
        if match.start() > 0 and raw[match.start() - 1] == "@":
            continue
        url = str(match.group(1) or "").strip().rstrip(".,)")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _extract_quoted_text(text: str) -> str:
    match = re.search(r"(?<!\w)['\"]([^'\"]{1,280})['\"](?!\w)", str(text or ""))
    return str(match.group(1) or "").strip() if match else ""


def _extract_app(text: str) -> str:
    low = _normalize_text(text)
    for alias, app in sorted(_APP_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"(?<!\w){re.escape(alias)}(?:[' ]?(?:yi|yı|yu|yü|i|ı|u|ü|ya|ye|a|e|da|de|dan|den))?(?!\w)", low):
            return app
    return ""


def _extract_app_sequence(text: str) -> list[str]:
    low = _normalize_text(text)
    matches: list[tuple[int, str]] = []
    for alias, app in _APP_ALIASES.items():
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?:[' ]?(?:yi|yı|yu|yü|i|ı|u|ü|ya|ye|a|e|da|de|dan|den))?(?!\w)", low):
            matches.append((int(match.start()), app))
    ordered: list[str] = []
    for _, app in sorted(matches, key=lambda item: item[0]):
        if not ordered or ordered[-1] != app:
            ordered.append(app)
    return ordered


def _infer_browser_app(text: str) -> str:
    app = _extract_app(text)
    if app in set(_BROWSER_ALIASES.values()):
        return app
    low = _normalize_text(text)
    if any(token in low for token in ("browser", "tarayıcı", "tarayici", "site", "sayfa", "web")):
        return "Safari"
    return ""


def _extract_known_page_url(text: str) -> str:
    low = _normalize_text(text)
    for alias, url in _KNOWN_PAGE_URLS.items():
        if alias in low:
            return url
    return ""


def _extract_known_page_urls(text: str) -> list[str]:
    low = _normalize_text(text)
    urls: list[str] = []
    seen: set[str] = set()
    for alias, url in _KNOWN_PAGE_URLS.items():
        if alias in low and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _extract_fill_text(text: str) -> str:
    quoted = _extract_quoted_text(text)
    if quoted:
        return quoted
    targeted_patterns = [
        r"(?:arama kutusuna|arama alanına|arama alanina|search field(?:ine)?|search box(?:una)?|search box)\s+(.+?)\s+(?:yaz|gir|doldur|type|fill)",
        r"(?:giriş alanına|giris alanina|login alanına|login alanina|input alanına|input alanina|field(?: içine| icine)?)\s+(.+?)\s+(?:yaz|gir|doldur|type|fill)",
    ]
    for pattern in targeted_patterns:
        match = re.search(pattern, str(text or ""), re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip(" \t\n\r'\"")
    patterns = [
        r"(?:arama kutusuna|search field(?:ine)?|search box(?:una)?|giriş alanına|giris alanina|giriş alanini|giris alanini|login alanına|login alanina|field(?: içine| icine)?|input(?: içine| icine)?|kutusuna|alanına|alanina)\s+(.+?)\s+(?:yaz|gir|doldur|type|fill)",
        r"(?:write|type|fill)\s+(.+?)\s+(?:into|in)\s+(?:the\s+)?(?:search field|search box|field|input|login field)",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip(" \t\n\r'\"")
    return ""


def _infer_field_label(text: str) -> str:
    low = _normalize_text(text)
    if any(token in low for token in ("arama", "search")):
        return "Search field"
    if any(token in low for token in ("giriş", "giris", "login")):
        return "Login field"
    if any(token in low for token in ("email", "e-posta", "eposta")):
        return "Email field"
    if any(token in low for token in ("şifre", "sifre", "password")):
        return "Password field"
    if any(token in low for token in ("field", "input", "alan", "kutu")):
        return "Input field"
    return ""


def _infer_selector(text: str, *, default: str = "") -> str:
    low = _normalize_text(text)
    for key, selector in _SELECTOR_MAP.items():
        if key in low:
            return selector
    return default


def _infer_button_label(text: str) -> str:
    low = _normalize_text(text)
    for key, label in _GENERIC_BUTTONS.items():
        if key in low:
            return label
    return ""


def _extract_named_field_values(text: str) -> list[dict[str, str]]:
    raw = str(text or "")
    matches: list[tuple[int, dict[str, str]]] = []
    for pattern, selector, field_label in _FIELD_VALUE_PATTERNS:
        for match in re.finditer(pattern, raw, re.IGNORECASE):
            value = str(match.group(1) or "").strip()
            if not value:
                continue
            matches.append(
                (
                    int(match.start()),
                    {
                        "selector": selector,
                        "field_label": field_label,
                        "text": value,
                    },
                )
            )
    ordered: list[dict[str, str]] = []
    seen_selectors: set[str] = set()
    for _, item in sorted(matches, key=lambda pair: pair[0]):
        selector = str(item.get("selector") or "").strip()
        if not selector or selector in seen_selectors:
            continue
        ordered.append(dict(item))
        seen_selectors.add(selector)
    return ordered


def _extract_button_sequence(text: str) -> list[dict[str, str]]:
    raw = _normalize_text(text)
    matches: list[tuple[int, dict[str, str]]] = []
    for pattern, label, selector in _BUTTON_SEQUENCE_PATTERNS:
        for match in re.finditer(pattern, raw, re.IGNORECASE):
            matches.append(
                (
                    int(match.start()),
                    {
                        "label": label,
                        "selector": selector,
                    },
                )
            )
    ordered: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, item in sorted(matches, key=lambda pair: pair[0]):
        key = (str(item.get("label") or "").strip(), str(item.get("selector") or "").strip())
        if key in seen:
            continue
        ordered.append(dict(item))
        seen.add(key)
    return ordered


def _extract_research_topic(text: str) -> str:
    raw = str(text or "").strip()
    quoted = _extract_quoted_text(raw)
    if quoted:
        return quoted
    patterns = [
        r"(.+?)\s+hakkında\s+(?:araştır(?:ma)?|arastir(?:ma)?|research)",
        r"(?:araştır(?:ma)?|arastir(?:ma)?|research)\s+(.+?)(?:\s+ve\s+|\s+ile\s+|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip(" \t\n\r.,")
    cleaned = re.sub(
        r"\b(?:araştır(?:ma)?|arastir(?:ma)?|research|rapor|report|belge|doküman|dokuman|oluştur|olustur|hazırla|hazirla|kaydet)\b",
        " ",
        raw,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split()).strip()


def _url_contains_value(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    host = host.replace("https://", "").replace("http://", "")
    return host.strip("/")


def _coerce_ui_state(latest_result: dict[str, Any], desktop_state: dict[str, Any]) -> dict[str, Any]:
    ui_state = latest_result.get("ui_state") if isinstance(latest_result.get("ui_state"), dict) else {}
    if ui_state:
        return dict(ui_state)
    post = latest_result.get("post_observation") if isinstance(latest_result.get("post_observation"), dict) else {}
    post_ui = post.get("ui_state") if isinstance(post.get("ui_state"), dict) else {}
    if post_ui:
        return dict(post_ui)
    last_ui = desktop_state.get("last_ui_state") if isinstance(desktop_state.get("last_ui_state"), dict) else {}
    return dict(last_ui)


def _coerce_browser_state(latest_result: dict[str, Any], browser_state: dict[str, Any]) -> dict[str, Any]:
    result_state = latest_result.get("browser_state") if isinstance(latest_result.get("browser_state"), dict) else {}
    return dict(result_state or browser_state or {})


def _result_search_blob(latest_result: dict[str, Any], ui_state: dict[str, Any], browser_state: dict[str, Any]) -> str:
    bits = [
        str(latest_result.get("message") or ""),
        str(latest_result.get("summary") or ""),
        str(latest_result.get("extracted_text") or ""),
        str(browser_state.get("visible_text") or ""),
        str(ui_state.get("summary") or ""),
    ]
    return _normalize_text(" ".join(bit for bit in bits if bit))


def _step_verify_satisfied(step: dict[str, Any], *, latest_result: dict[str, Any], desktop_state: dict[str, Any], browser_state: dict[str, Any]) -> bool:
    verify = step.get("verify") if isinstance(step.get("verify"), dict) else {}
    if not verify:
        return False
    ui_state = _coerce_ui_state(latest_result, desktop_state)
    current_browser = _coerce_browser_state(latest_result, browser_state)
    blob = _result_search_blob(latest_result, ui_state, current_browser)
    if "frontmost_app" in verify and _normalize_text(ui_state.get("frontmost_app")) != _normalize_text(verify.get("frontmost_app")):
        return False
    if "window_title_contains" in verify:
        current_window = str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or current_browser.get("title") or "")
        if _normalize_text(verify.get("window_title_contains")) not in _normalize_text(current_window):
            return False
    if "url_contains" in verify and _normalize_text(verify.get("url_contains")) not in _normalize_text(current_browser.get("url")):
        return False
    if "title_contains" in verify and _normalize_text(verify.get("title_contains")) not in _normalize_text(current_browser.get("title")):
        return False
    if "text_contains" in verify and _normalize_text(verify.get("text_contains")) not in blob:
        return False
    if "goal_achieved" in verify and bool(latest_result.get("goal_achieved")) != bool(verify.get("goal_achieved")):
        return False
    if "fallback_used" in verify:
        fallback = latest_result.get("fallback") if isinstance(latest_result.get("fallback"), dict) else {}
        if bool(fallback.get("used")) != bool(verify.get("fallback_used")):
            return False
        if bool(verify.get("fallback_used")):
            if latest_result.get("success") is False:
                return False
            if "goal_achieved" in latest_result and not bool(latest_result.get("goal_achieved")) and _normalize_text(latest_result.get("status")) != "success":
                return False
    return True


def _coerce_task_state_for_replan(latest_result: dict[str, Any], desktop_state: dict[str, Any]) -> dict[str, Any]:
    result_task_state = latest_result.get("task_state") if isinstance(latest_result.get("task_state"), dict) else {}
    desktop_task_state = desktop_state.get("current_task_state") if isinstance(desktop_state.get("current_task_state"), dict) else {}
    merged = dict(desktop_task_state)
    merged.update(result_task_state)
    if not isinstance(merged.get("last_ui_state"), dict):
        merged["last_ui_state"] = dict(desktop_state.get("last_ui_state") or {})
    if not isinstance(merged.get("last_target_cache"), dict):
        merged["last_target_cache"] = dict(desktop_state.get("target_cache") or {})
    return merged


def _screen_recovery_step_from_browser(step: dict[str, Any], *, latest_result: dict[str, Any]) -> dict[str, Any]:
    selector = str(step.get("selector") or "").strip()
    url = str(step.get("url") or "").strip()
    action = str(step.get("action") or "").strip().lower()
    instruction = str(step.get("screen_instruction") or "").strip()
    if not instruction:
        if action == "open" and url:
            instruction = f"Tarayicida {url} adresinin acildigini dogrula"
        elif action == "click" and selector:
            instruction = f"{selector} ile ilgili kontrolu ekranda bul ve tikla"
        elif action == "type" and str(step.get("text") or "").strip():
            instruction = f'"{str(step.get("text") or "").strip()}" metnini tarayicidaki uygun alana yaz'
        else:
            instruction = "Tarayicidaki yuzeyi ekranda kontrol et ve devam et"
    verify = dict(step.get("verify") or {}) if isinstance(step.get("verify"), dict) else {}
    verify.pop("fallback_used", None)
    verify["goal_achieved"] = True
    if "url_contains" in verify:
        verify.pop("url_contains", None)
    if "title_contains" in verify and "window_title_contains" not in verify:
        verify["window_title_contains"] = str(verify.pop("title_contains") or "").strip()
    expected_title = str(step.get("expected_title_contains") or "").strip()
    if expected_title and "window_title_contains" not in verify:
        verify["window_title_contains"] = expected_title
    expected_text = str(step.get("expected_text") or "").strip()
    if expected_text and "text_contains" not in verify:
        verify["text_contains"] = expected_text
    return {
        "kind": "screen",
        "name": f"screen_fallback_{_slugify(str(step.get('name') or action or 'browser'))}",
        "instruction": instruction,
        "mode": "inspect" if action == "open" else "control",
        "verify": verify,
        "repair_policy": {"max_retries": 1},
        "task_state": _coerce_task_state_for_replan(latest_result, {}),
        "source_step_kind": "browser",
        "fallback_reason": str(latest_result.get("error_code") or "").strip(),
    }


class LiveOperatorTaskPlanner:
    def __init__(self, *, task_runtime: OperatorTaskRuntime | None = None) -> None:
        self.task_runtime = task_runtime or OperatorTaskRuntime()

    def plan_request(self, request: str) -> dict[str, Any]:
        raw_request = str(request or "").strip()
        planning_request = _sanitize_request_for_planning(raw_request) or raw_request
        low = _normalize_text(planning_request)
        app_name = _extract_app(low)
        app_sequence = _extract_app_sequence(planning_request)
        browser_app = _infer_browser_app(low)
        explicit_urls = _extract_urls(planning_request)
        explicit_url = explicit_urls[0] if explicit_urls else ""
        known_urls = _extract_known_page_urls(low)
        inferred_url = explicit_url or (known_urls[0] if known_urls else "")
        urls = explicit_urls + [item for item in known_urls if item not in set(explicit_urls)]
        typed_text = _extract_fill_text(planning_request)
        named_field_values = _extract_named_field_values(planning_request)
        field_label = _infer_field_label(planning_request)
        selector = _infer_selector(planning_request, default="#q" if field_label == "Search field" else "")
        button_label = _infer_button_label(planning_request)
        button_sequence = _extract_button_sequence(planning_request)
        research_topic = _extract_research_topic(planning_request)
        matched_rules: list[str] = []
        assumptions: list[str] = []
        missing_inputs: list[str] = []
        steps: list[dict[str, Any]] = []

        has_dialog_word = any(token in low for token in ("diyalog", "diyaloğ", "dialog"))
        wants_upload_dialog = ("upload" in low and has_dialog_word) or ("yükleme" in low and has_dialog_word)
        wants_open = any(token in low for token in (" aç", "aç", "ac", "open", "git", "siteye git", "navigate"))
        wants_type = bool(typed_text) or any(token in low for token in ("yaz", "doldur", "type", "fill", "gir"))
        wants_inspect = any(token in low for token in ("ekrana bak", "doğru pencereyi bul", "dogru pencereyi bul", "inspect", "look at the screen"))
        wants_continue = any(token in low for token in ("devam et", "continue", "next", "ileri"))
        wants_click = any(token in low for token in ("tikla", "tıkla", "click", "onayla", "confirm", "devam et", "continue", "submit", "save", "open"))
        wants_completion_check = any(token in low for token in ("doğrula", "dogrula", "verify", "tamamlandı", "tamamlandi", "complete"))
        wants_research = any(token in low for token in ("araştır", "arastir", "research", "incele", "rapor", "report"))
        wants_document = any(token in low for token in ("belge", "doküman", "dokuman", "rapor", "report", "kaydet", "olustur", "oluştur", "hazırla", "hazirla"))
        browser_preferred = bool(inferred_url) or wants_upload_dialog or any(token in low for token in ("browser", "tarayıcı", "tarayici", "site", "sayfa", "web", "url", "upload"))
        open_apps = app_sequence or ([browser_app] if browser_app else ([app_name] if app_name else []))

        if wants_research and wants_document and research_topic:
            matched_rules.append("research_document_flow")
            steps.append(
                {
                    "kind": "system",
                    "name": "research_document_delivery",
                    "tool": "research_document_delivery",
                    "params": {
                        "topic": research_topic,
                        "language": "tr",
                    },
                    "verify": {"artifact_count_min": 2, "artifacts_exist": True, "artifacts_non_empty": True},
                    "repair_policy": {"max_retries": 1},
                }
            )
        elif wants_upload_dialog and named_field_values and len(urls) >= 2:
            matched_rules.append("login_continue_upload_flow")
            login_url = str(urls[0] or "").strip()
            upload_url = str(urls[1] or "").strip()
            for app in open_apps or ["Safari"]:
                steps.append(
                    {
                        "kind": "system",
                        "name": f"open_{_slugify(app)}",
                        "tool": "open_app",
                        "params": {"app_name": app},
                        "verify": {"frontmost_app": app},
                    }
                )
            steps.append(
                {
                    "kind": "browser",
                    "name": "open_login_page",
                    "action": "open",
                    "url": login_url,
                    "expected_url_contains": _url_contains_value(login_url),
                    "verify": {"url_contains": _url_contains_value(login_url)},
                    "repair_policy": {"max_retries": 1},
                }
            )
            for item in named_field_values:
                steps.append(
                    {
                        "kind": "browser",
                        "name": f"fill_{_slugify(str(item.get('selector') or '').strip('#'))}",
                        "action": "type",
                        "selector": str(item.get("selector") or "").strip(),
                        "text": str(item.get("text") or "").strip(),
                        "verify": {"text_contains": str(item.get("text") or "").strip()},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            for item in button_sequence:
                selector_value = str(item.get("selector") or "").strip()
                if selector_value in {"#open", "#save"}:
                    continue
                steps.append(
                    {
                        "kind": "browser",
                        "name": f"click_{_slugify(str(item.get('label') or selector_value).strip())}",
                        "action": "click",
                        "selector": selector_value,
                        "verify": {},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            steps.append(
                {
                    "kind": "browser",
                    "name": "open_upload_page",
                    "action": "open",
                    "url": upload_url,
                    "expected_url_contains": _url_contains_value(upload_url),
                    "expected_title_contains": "Upload",
                    "verify": {"url_contains": _url_contains_value(upload_url), "title_contains": "Upload"},
                    "repair_policy": {"max_retries": 1},
                }
            )
            steps.append(
                {
                    "kind": "browser",
                    "name": "confirm_upload_dialog",
                    "action": "click",
                    "selector": "#upload",
                    "native_dialog_expected": True,
                    "screen_instruction": "Open butonuna tikla",
                    "verify": {"fallback_used": True, "window_title_contains": "Upload"},
                    "repair_policy": {"max_retries": 1},
                }
            )
            if wants_completion_check:
                steps.append(
                    {
                        "kind": "browser",
                        "name": "verify_upload_completion",
                        "action": "status",
                        "verify": {"title_contains": "Upload Complete", "text_contains": "Upload Complete"},
                        "repair_policy": {"max_retries": 1},
                    }
                )
        elif wants_upload_dialog:
            matched_rules.append("upload_dialog_flow")
            if not browser_app:
                browser_app = "Safari"
                assumptions.append("Browser app defaulted to Safari for upload flow.")
            if not open_apps:
                open_apps = [browser_app]
            if not inferred_url:
                inferred_url = "https://upload.local"
                assumptions.append("Upload page URL defaulted to https://upload.local.")
            for app in open_apps:
                steps.append(
                    {
                        "kind": "system",
                        "name": f"open_{_slugify(app)}",
                        "tool": "open_app",
                        "params": {"app_name": app},
                        "verify": {"frontmost_app": app},
                    }
                )
            steps.append(
                {
                    "kind": "browser",
                    "name": "open_upload_page",
                    "action": "open",
                    "url": inferred_url,
                    "expected_url_contains": _url_contains_value(inferred_url),
                    "expected_title_contains": "Upload",
                    "verify": {"url_contains": _url_contains_value(inferred_url), "title_contains": "Upload"},
                    "repair_policy": {"max_retries": 1},
                }
            )
            steps.append(
                {
                    "kind": "browser",
                    "name": "confirm_upload_dialog",
                    "action": "click",
                    "selector": "#upload",
                    "native_dialog_expected": True,
                    "screen_instruction": "Open butonuna tikla",
                    "verify": {"fallback_used": True, "window_title_contains": "Upload"},
                    "repair_policy": {"max_retries": 1},
                }
            )
            extra_buttons = [dict(item) for item in button_sequence if str(item.get("selector") or "").strip() not in {"#login"}]
            for item in extra_buttons:
                steps.append(
                    {
                        "kind": "browser",
                        "name": f"click_{_slugify(str(item.get('label') or item.get('selector') or '').strip())}",
                        "action": "click",
                        "selector": str(item.get("selector") or "").strip(),
                        "verify": {},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            if wants_completion_check:
                steps.append(
                    {
                        "kind": "browser",
                        "name": "verify_upload_completion",
                        "action": "status",
                        "verify": {"title_contains": "Upload Complete", "text_contains": "Upload Complete"},
                        "repair_policy": {"max_retries": 1},
                    }
                )
        elif browser_preferred and inferred_url:
            matched_rules.append("browser_navigation_flow")
            for app in open_apps:
                steps.append(
                    {
                        "kind": "system",
                        "name": f"open_{_slugify(app)}",
                        "tool": "open_app",
                        "params": {"app_name": app},
                        "verify": {"frontmost_app": app},
                    }
                )
            steps.append(
                {
                    "kind": "browser",
                    "name": "open_page",
                    "action": "open",
                    "url": inferred_url,
                    "expected_url_contains": _url_contains_value(inferred_url),
                    "expected_title_contains": "Upload" if "upload" in low else ("Search" if "search" in low or "arama" in low else ""),
                    "verify": {"url_contains": _url_contains_value(inferred_url)},
                    "repair_policy": {"max_retries": 1},
                }
            )
            if named_field_values:
                matched_rules.append("browser_named_fill_steps")
                for item in named_field_values:
                    steps.append(
                        {
                            "kind": "browser",
                            "name": f"fill_{_slugify(str(item.get('selector') or '').strip('#'))}",
                            "action": "type",
                            "selector": str(item.get("selector") or "").strip(),
                            "text": str(item.get("text") or "").strip(),
                            "verify": {"text_contains": str(item.get("text") or "").strip()},
                            "repair_policy": {"max_retries": 1},
                        }
                    )
            elif wants_type and typed_text and selector:
                matched_rules.append("browser_fill_step")
                steps.append(
                    {
                        "kind": "browser",
                        "name": "fill_field",
                        "action": "type",
                        "selector": selector,
                        "text": typed_text,
                        "verify": {"text_contains": typed_text},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            elif wants_type and not typed_text:
                missing_inputs.append("text")
                assumptions.append("Fill step degraded to screen inspect because input text is missing.")
                steps.append(
                    {
                        "kind": "screen",
                        "name": "inspect_field_before_fill",
                        "instruction": "ekrana bak",
                        "mode": "inspect",
                        "verify": {},
                    }
                )
            if button_sequence:
                matched_rules.append("browser_click_steps")
                for item in button_sequence:
                    click_selector = str(item.get("selector") or "").strip()
                    click_label = str(item.get("label") or "").strip()
                    if not click_selector:
                        continue
                    steps.append(
                        {
                            "kind": "browser",
                            "name": f"click_{_slugify(click_label or click_selector.strip('#'))}",
                            "action": "click",
                            "selector": click_selector,
                            "verify": {},
                            "repair_policy": {"max_retries": 1},
                        }
                    )
            elif ("search" in low or "arama" in low or "submit" in low or "gönder" in low or "gonder" in low) and selector and (typed_text or named_field_values):
                matched_rules.append("browser_submit_step")
                steps.append(
                    {
                        "kind": "browser",
                        "name": "submit_form",
                        "action": "submit",
                        "selector": selector,
                        "expected_text": typed_text,
                        "verify": {"text_contains": typed_text} if typed_text else {},
                        "repair_policy": {"max_retries": 1},
                    }
                )
        elif (app_name or browser_app) and (wants_type or wants_click or wants_inspect):
            matched_rules.append("desktop_operator_flow")
            target_app = app_name or browser_app
            for app in (app_sequence or ([target_app] if target_app else [])):
                steps.append(
                    {
                        "kind": "system",
                        "name": f"open_{_slugify(app)}",
                        "tool": "open_app",
                        "params": {"app_name": app},
                        "verify": {"frontmost_app": app},
                    }
                )
            if app_sequence:
                target_app = app_sequence[-1]
            if wants_inspect:
                steps.append(
                    {
                        "kind": "screen",
                        "name": "inspect_screen",
                        "instruction": "ekrana bak",
                        "mode": "inspect",
                        "verify": {},
                    }
                )
            if wants_type and typed_text:
                if not field_label:
                    field_label = "Input field"
                    assumptions.append("Field label defaulted to Input field.")
                matched_rules.append("screen_fill_step")
                steps.append(
                    {
                        "kind": "screen",
                        "name": "fill_screen_field",
                        "instruction": f'{field_label} icine "{typed_text}" yaz',
                        "verify": {"text_contains": typed_text, **({"frontmost_app": target_app} if target_app else {})},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            elif wants_type and not typed_text:
                missing_inputs.append("text")
                assumptions.append("Typed text missing; planner kept the flow bounded with inspect only.")
            if wants_click or wants_continue:
                label = button_label or ("Continue" if wants_continue else "")
                instruction = f"{label} butonuna tikla" if label else raw_request
                matched_rules.append("screen_click_step")
                steps.append(
                    {
                        "kind": "screen",
                        "name": f"click_{_slugify(label or 'target')}",
                        "instruction": instruction,
                        "verify": {"frontmost_app": target_app} if target_app else {},
                        "repair_policy": {"max_retries": 1},
                    }
                )
        else:
            matched_rules.append("safe_inspect_fallback")
            if browser_app:
                steps.append(
                    {
                        "kind": "system",
                        "name": f"open_{_slugify(browser_app)}",
                        "tool": "open_app",
                        "params": {"app_name": browser_app},
                        "verify": {"frontmost_app": browser_app},
                    }
                )
            steps.append(
                {
                    "kind": "screen",
                    "name": "inspect_screen",
                    "instruction": "ekrana bak",
                    "mode": "inspect",
                    "verify": {},
                }
            )
            if wants_continue:
                steps.append(
                    {
                        "kind": "screen",
                        "name": "continue_in_frontmost_window",
                        "instruction": "Continue butonuna tikla",
                        "verify": {},
                        "repair_policy": {"max_retries": 1},
                    }
                )
            if wants_type and not typed_text:
                missing_inputs.append("text")
            if browser_preferred and not inferred_url and any(token in low for token in ("site", "sayfa", "web")):
                missing_inputs.append("url")
                assumptions.append("URL missing; planner avoided blind navigation.")

        if browser_preferred and not inferred_url and any(token in low for token in ("site", "sayfa", "web", "upload")):
            if "url" not in missing_inputs:
                missing_inputs.append("url")
            if "URL missing; planner avoided blind navigation." not in assumptions:
                assumptions.append("URL missing; planner avoided blind navigation.")

        if missing_inputs and not any(str(step.get("mode") or "").strip().lower() == "inspect" for step in steps):
            steps.append(
                {
                    "kind": "screen",
                    "name": "inspect_before_manual_follow_up",
                    "instruction": "ekrana bak",
                    "mode": "inspect",
                    "verify": {},
                }
            )
            matched_rules.append("bounded_inspect_on_missing_inputs")

        if not steps:
            steps.append(
                {
                    "kind": "screen",
                    "name": "inspect_screen",
                    "instruction": "ekrana bak",
                    "mode": "inspect",
                    "verify": {},
                }
            )
            matched_rules.append("minimal_inspect_plan")

        for step in steps:
            step.setdefault("verify", {})
            if "repair_policy" in step:
                policy = step.get("repair_policy") if isinstance(step.get("repair_policy"), dict) else {}
                policy.setdefault("max_retries", 1)
                step["repair_policy"] = policy

        planning_trace = {
            "request": raw_request,
            "planning_request": planning_request,
            "matched_rules": matched_rules,
            "assumptions": assumptions,
            "missing_inputs": sorted(dict.fromkeys(missing_inputs)),
            "extracted": {
                "app_name": app_name,
                "app_sequence": app_sequence,
                "browser_app": browser_app,
                "url": inferred_url,
                "urls": urls,
                "typed_text": typed_text,
                "named_field_values": named_field_values,
                "field_label": field_label,
                "selector": selector,
                "button_label": button_label,
                "button_sequence": button_sequence,
                "research_topic": research_topic,
            },
            "bounded": True,
            "safe_mode": "deterministic",
        }
        name = _slugify(planning_request)[:64]
        rationale = " -> ".join(matched_rules) if matched_rules else "deterministic_fallback"
        return {
            "name": name,
            "goal": planning_request,
            "steps": steps,
            "planning_trace": planning_trace,
            "rationale": rationale,
        }

    def replan_remaining(
        self,
        task_state: dict[str, Any],
        latest_result: dict[str, Any],
        latest_verification: dict[str, Any],
        desktop_state: dict[str, Any],
        browser_state: dict[str, Any],
    ) -> dict[str, Any]:
        state = dict(task_state or {})
        latest = dict(latest_result or {})
        verification = dict(latest_verification or {})
        desktop = dict(desktop_state or {})
        current_browser = dict(browser_state or {})
        step_defs = [dict(item) for item in list(state.get("step_definitions") or []) if isinstance(item, dict)]
        step_index = max(1, int(state.get("current_step") or 1))
        if step_index > len(step_defs):
            return {"remaining_steps": [], "rationale": "no_remaining_steps", "replan_trace": {"trigger": "none", "step_index": step_index}}

        trigger = "success" if bool(verification.get("ok")) else "failure"
        failed_codes = [str(code).strip() for code in list(verification.get("failed_codes") or []) if str(code).strip()]
        failed_code_set = set(failed_codes)
        trace: dict[str, Any] = {
            "trigger": trigger,
            "step_index": step_index,
            "failed_codes": failed_codes,
            "current_step_name": str(step_defs[step_index - 1].get("name") or f"step_{step_index}"),
            "actions": [],
        }

        if trigger == "success":
            remaining = [dict(item) for item in step_defs[step_index:]]
            skipped: list[str] = []
            while remaining and _step_verify_satisfied(remaining[0], latest_result=latest, desktop_state=desktop, browser_state=current_browser):
                skipped.append(str(remaining[0].get("name") or f"step_{step_index + len(skipped) + 1}"))
                remaining = remaining[1:]
            trace["actions"].append({"kind": "skip_already_satisfied_steps", "skipped": skipped})
            return {
                "remaining_steps": remaining,
                "rationale": "skip_already_satisfied_steps" if skipped else "keep_remaining_steps",
                "replan_trace": trace,
            }

        step = dict(step_defs[step_index - 1] or {})
        following = [dict(item) for item in step_defs[step_index:]]
        replacement: list[dict[str, Any]] = []
        recovery_task_state = _coerce_task_state_for_replan(latest, desktop)
        ui_state = _coerce_ui_state(latest, desktop)
        current_browser = _coerce_browser_state(latest, current_browser)
        expected_app = str(((step.get("verify") if isinstance(step.get("verify"), dict) else {}) or {}).get("frontmost_app") or ui_state.get("frontmost_app") or desktop.get("frontmost_app") or "").strip()

        if _step_verify_satisfied(step, latest_result=latest, desktop_state=desktop, browser_state=current_browser):
            trace["actions"].append({"kind": "mark_failed_step_satisfied_from_observation"})
            return {
                "remaining_steps": following,
                "rationale": "failed_step_already_satisfied_from_latest_observation",
                "replan_trace": trace,
            }

        current_app = _normalize_text(ui_state.get("frontmost_app") or desktop.get("frontmost_app") or "")
        needs_app_recovery = FailureCode.WRONG_APP_CONTEXT.value in failed_codes or (
            FailureCode.WRONG_WINDOW_CONTEXT.value in failed_codes and expected_app and _normalize_text(expected_app) and _normalize_text(expected_app) != current_app
        )
        if needs_app_recovery:
            if expected_app:
                replacement.append(
                    {
                        "kind": "system",
                        "name": f"recover_focus_{_slugify(expected_app)}",
                        "tool": "open_app",
                        "params": {"app_name": expected_app},
                        "verify": {"frontmost_app": expected_app},
                    }
                )
                trace["actions"].append({"kind": "restore_frontmost_app", "app_name": expected_app})

        if str(step.get("kind") or "").strip().lower() == "screen":
            if FailureCode.UI_TARGET_NOT_FOUND.value in failed_codes:
                replacement.append(
                    {
                        "kind": "screen",
                        "name": f"reobserve_{_slugify(str(step.get('name') or 'screen'))}",
                        "instruction": "ekrana bak",
                        "mode": "inspect",
                        "verify": {},
                    }
                )
                trace["actions"].append({"kind": "reobserve_screen"})
            if failed_code_set & {
                FailureCode.UI_TARGET_NOT_FOUND.value,
                FailureCode.NO_VISUAL_CHANGE.value,
                FailureCode.TEXT_NOT_VERIFIED.value,
                FailureCode.ARTIFACT_MISSING.value,
                FailureCode.WRONG_APP_CONTEXT.value,
                FailureCode.WRONG_WINDOW_CONTEXT.value,
            }:
                repaired_step = dict(step)
                repaired_step["task_state"] = recovery_task_state
                if FailureCode.TEXT_NOT_VERIFIED.value in failed_code_set or FailureCode.ARTIFACT_MISSING.value in failed_code_set:
                    repaired_step["max_retries_per_action"] = max(1, int(step.get("max_retries_per_action") or 1))
                replacement.append(repaired_step)
                trace["actions"].append({"kind": "rerun_screen_step_with_latest_observation", "step": str(step.get("name") or "")})

        elif str(step.get("kind") or "").strip().lower() == "browser":
            if failed_code_set & {
                FailureCode.DOM_UNAVAILABLE.value,
                FailureCode.NATIVE_DIALOG_REQUIRED.value,
                FailureCode.UNCONTROLLED_BROWSER_CHROME.value,
            }:
                replacement.append(_screen_recovery_step_from_browser(step, latest_result=latest))
                trace["actions"].append({"kind": "rewrite_browser_step_to_screen_fallback"})
            elif failed_code_set & {
                FailureCode.SUBMIT_NOT_VERIFIED.value,
                FailureCode.NAVIGATION_NOT_VERIFIED.value,
                FailureCode.TEXT_NOT_VERIFIED.value,
            }:
                if _step_verify_satisfied(step, latest_result={"browser_state": current_browser, "ui_state": ui_state}, desktop_state=desktop, browser_state=current_browser):
                    trace["actions"].append({"kind": "drop_browser_step_already_satisfied"})
                else:
                    replacement.append(
                        {
                            "kind": "browser",
                            "name": f"status_check_{_slugify(str(step.get('name') or 'browser'))}",
                            "action": "status",
                            "verify": {},
                        }
                    )
                    repaired_step = dict(step)
                    repaired_step["replanned_after_state_check"] = True
                    replacement.append(repaired_step)
                    trace["actions"].append({"kind": "rerun_browser_step_after_state_check", "url": str(current_browser.get("url") or "")})

        if not replacement:
            trace["actions"].append({"kind": "keep_failed_step", "reason": "no_rule_matched"})
            replacement = [dict(step)]

        return {
            "remaining_steps": replacement + following,
            "rationale": str(trace["actions"][0]["kind"] if trace["actions"] else "keep_failed_step"),
            "replan_trace": trace,
        }

    async def start_request(
        self,
        request: str,
        *,
        task_id: str = "",
        screen_services: Any = None,
        browser_services: Any = None,
        clear_live_state: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan_request(request)
        metadata = {
            "request": str(request or "").strip(),
            "planner": "live_operator_task_planner_v1",
            "plan": {"name": str(plan.get("name") or ""), "goal": str(plan.get("goal") or ""), "steps": [dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)]},
            "planning_trace": dict(plan.get("planning_trace") or {}),
        }
        result = await self.task_runtime.start_task(
            goal=str(plan.get("goal") or request or "").strip(),
            steps=[dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)],
            name=str(plan.get("name") or "operator-task").strip(),
            task_id=task_id,
            metadata=metadata,
            screen_services=screen_services,
            browser_services=browser_services,
            clear_live_state=clear_live_state,
        )
        comparison = await self.compare_plan_to_progress(str(result.get("task_id") or ""))
        return {
            "success": bool(result.get("success")),
            "status": str(result.get("status") or ("success" if result.get("success") else "failed")),
            "task_id": str(result.get("task_id") or "").strip(),
            "plan": plan,
            "planning_trace": dict(plan.get("planning_trace") or {}),
            "comparison": comparison,
            "task_result": result,
        }

    async def resume_request(
        self,
        task_id: str,
        *,
        screen_services: Any = None,
        browser_services: Any = None,
    ) -> dict[str, Any]:
        result = await self.task_runtime.resume_task(task_id, screen_services=screen_services, browser_services=browser_services)
        inspected = await self.inspect_task_plan(task_id)
        comparison = await self.compare_plan_to_progress(task_id)
        return {
            "success": bool(result.get("success")),
            "status": str(result.get("status") or ("success" if result.get("success") else "failed")),
            "task_id": str(task_id or "").strip(),
            "plan": dict(inspected.get("plan") or {}),
            "planning_trace": dict(inspected.get("planning_trace") or {}),
            "comparison": comparison,
            "task_result": result,
        }

    async def inspect_task_plan(self, task_id: str) -> dict[str, Any]:
        state = await self.task_runtime.get_task_state(task_id)
        metadata = dict(state.get("metadata") or {}) if isinstance(state.get("metadata"), dict) else {}
        return {
            "task_id": str(task_id or "").strip(),
            "plan": dict(metadata.get("plan") or {}),
            "planning_trace": dict(metadata.get("planning_trace") or {}),
            "status": str(state.get("status") or "").strip(),
        }

    async def compare_plan_to_progress(self, task_id: str) -> dict[str, Any]:
        state = await self.task_runtime.get_task_state(task_id)
        metadata = dict(state.get("metadata") or {}) if isinstance(state.get("metadata"), dict) else {}
        plan = dict(metadata.get("plan") or {}) if isinstance(metadata.get("plan"), dict) else {}
        step_defs = [dict(item) for item in list(state.get("step_definitions") or []) if isinstance(item, dict)]
        step_records = [dict(item) for item in list(state.get("steps") or []) if isinstance(item, dict)]
        rows: list[dict[str, Any]] = []
        for index, definition in enumerate(step_defs, start=1):
            record = step_records[index - 1] if index - 1 < len(step_records) else {}
            verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
            rows.append(
                {
                    "step_index": index,
                    "name": str(definition.get("name") or record.get("name") or f"step_{index}").strip(),
                    "kind": str(definition.get("kind") or record.get("kind") or "").strip(),
                    "planned_verify": dict(definition.get("verify") or {}) if isinstance(definition.get("verify"), dict) else {},
                    "status": str(record.get("status") or "pending").strip(),
                    "attempts": max(0, int(record.get("attempts") or 0)),
                    "verified": bool(verification.get("ok")),
                    "error_code": str(record.get("error_code") or "").strip(),
                }
            )
        completed = [row for row in rows if row["status"] == "completed"]
        return {
            "task_id": str(task_id or "").strip(),
            "plan_name": str(plan.get("name") or state.get("name") or "").strip(),
            "planned_step_count": len(rows),
            "completed_step_count": len(completed),
            "current_step": max(0, int(state.get("current_step") or 0)),
            "status": str(state.get("status") or "").strip(),
            "replan_count": max(0, int(state.get("replan_count") or 0)),
            "steps": rows,
        }


__all__ = ["LiveOperatorTaskPlanner"]
