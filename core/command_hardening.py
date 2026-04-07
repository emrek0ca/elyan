from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


_CHAT_META_PREFIXES = (
    "deliverable spec:",
    "done criteria:",
    "başarı kriteri:",
    "success criteria:",
    "sistem notu:",
    "system note:",
    "analiz ediyorum",
    "şimdi size",
    "simdi size",
    "tabii ki",
    "elbette",
    "öncelikle",
    "oncelikle",
    "kısaca",
    "kisaca",
    "here's",
    "here is",
    "as an ai",
    "as a language model",
)

_CHAT_JSON_KEYS = ("message", "text", "answer", "response", "reply", "content")
_CHAT_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_CHAT_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[:\-\s|]+\|[:\-\s|]+\s*$")
_CHAT_CODE_BLOCK_RE = re.compile(r"```[\w-]*\n.*?```", flags=re.DOTALL)
_CHAT_JSON_LIKE_RE = re.compile(r"^\s*[\[{]")

_GREETING_MARKERS = (
    "merhaba",
    "selam",
    "hey",
    "hi",
    "hello",
    "naber",
    "nbr",
    "nasılsın",
    "nasilsin",
    "nasılsınız",
    "nasilsiniz",
    "iyi akşamlar",
    "günaydın",
    "iyi günler",
)
_QUESTION_MARKERS = (
    "nedir",
    "kimdir",
    "nasıl",
    "nasil",
    "neden",
    "niye",
    "hangi",
    "kaç",
    "kac",
    "what",
    "who",
    "why",
    "how",
    "when",
    "where",
)
_SCREEN_MARKERS = (
    "ekran",
    "screen",
    "screenshot",
    "pano",
    "clipboard",
    "imlec",
    "cursor",
    "mouse",
    "tıkla",
    "tikla",
    "click",
    "yaz",
    "type",
    "sekme",
    "tab",
    "window",
    "pencere",
    "ui",
    "buton",
    "butonu",
    "butonuna",
)
_BROWSER_MARKERS = (
    "browser",
    "tarayıcı",
    "tarayici",
    "safari",
    "chrome",
    "firefox",
    "arc",
    "url",
    "web",
    "site",
    "sayfa",
    "page",
    "open url",
)
_FILE_MARKERS = (
    "dosya",
    "klasör",
    "klasor",
    "kaydet",
    "oku",
    "yaz",
    "sil",
    "listele",
    "folder",
    "file",
    "path",
)
_RESEARCH_MARKERS = (
    "araştır",
    "arastir",
    "research",
    "incele",
    "rapor",
    "kaynak",
    "makale",
    "literatür",
    "literatur",
    "karşılaştır",
    "karsilastir",
)
_CODE_MARKERS = (
    "kod",
    "code",
    "python",
    "javascript",
    "typescript",
    "react",
    "debug",
    "refactor",
    "implement",
    "script",
    "function",
    "class",
)

_WEB_BUILD_VERBS = (
    "yap",
    "yaz",
    "oluştur",
    "olustur",
    "üret",
    "uret",
    "tasarla",
    "geliştir",
    "gelistir",
    "hazırla",
    "hazirla",
    "kaydet",
    "create",
    "build",
    "make",
)

_WEB_BUILD_MARKERS = (
    "landing page",
    "landing",
    "frontend",
    "web sitesi",
    "web sayfası",
    "web sayfasi",
    "website",
    "html",
    "css",
    "javascript",
    "js",
    "ui",
)
_TASK_MARKERS = (
    "aç",
    "ac",
    "kapat",
    "başlat",
    "baslat",
    "odaklan",
    "focus",
    "planla",
    "uygula",
    "workflow",
    "otomasyon",
    "automation",
    "adım",
    "adim",
)
_CAPTCHA_MARKERS = (
    "captcha",
    "2fa",
    "two factor",
    "two-factor",
    "otp",
    "one time password",
    "one-time password",
    "verification code",
    "auth code",
    "sms kod",
    "authenticator",
)
_AUTH_MARKERS = (
    "giriş yap",
    "giris yap",
    "oturum aç",
    "oturum ac",
    "login",
    "login ol",
    "log in",
    "sign in",
    "sign-in",
    "authenticate",
    "kimlik doğrula",
    "kimlik dogrula",
    "yetkilendir",
    "authentication",
)
_PRIVILEGE_MARKERS = (
    "sudo",
    "run as root",
    "run as administrator",
    "administrator privileges",
    "admin privileges",
    "privilege escalation",
    "elevated privileges",
)
_VOICE_MARKERS = (
    "microphone",
    "mikrofon",
    "voice",
    "audio",
    "ses kaydı",
    "ses kaydi",
    "record audio",
    "listen to microphone",
)
_DESTRUCTIVE_MARKERS = (
    "hepsini sil",
    "tümünü sil",
    "tumunu sil",
    "delete all",
    "remove all",
    "wipe",
    "factory reset",
    "format disk",
    "erase all",
    "purge all",
)
_INACCESSIBLE_UI_MARKERS = (
    "görünmeyen",
    "gorunmeyen",
    "hidden ui",
    "invisible ui",
    "erişilemeyen",
    "erisilemeyen",
    "no accessibility",
    "without accessibility",
    "blind click",
    "blindly click",
    "ekran dışı",
    "screenless",
)
_UI_TOOL_NAMES = {
    "mouse_click",
    "mouse_move",
    "scroll",
    "scroll_page",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r\n", "\n").strip().lower().split())


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    low = _normalize_text(text)
    return any(marker in low for marker in markers if marker)


def _extract_json_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text or text[:1] not in {"{", "["}:
        return text
    try:
        parsed = json.loads(text)
    except Exception:
        return text
    extracted = ""
    if isinstance(parsed, dict):
        for key in _CHAT_JSON_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                extracted = value.strip()
                break
        if not extracted:
            for value in parsed.values():
                if isinstance(value, str) and value.strip():
                    extracted = value.strip()
                    break
    elif isinstance(parsed, list):
        values = [str(item).strip() for item in parsed if isinstance(item, str) and str(item).strip()]
        if values:
            extracted = " ".join(values[:2])
    return extracted or text


def _looks_like_meta_line(line: str) -> bool:
    low = _normalize_text(line)
    if not low:
        return True
    if low.startswith(_CHAT_META_PREFIXES):
        return True
    if any(marker in low for marker in ("completion gate failed", "verification failed", "verify failed", "plan failed")):
        return True
    if low.startswith(("analiz", "şimdi", "simdi", "tabii", "elbette", "öncelikle", "oncelikle")):
        return True
    if low in {"- kullanıcıya yardımcı olmak", "- kullanıcının ihtiyacını belirlemek"}:
        return True
    return False


def _dedupe_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for sentence in sentences:
        piece = sentence.strip()
        if not piece:
            continue
        normalized = re.sub(r"\s+", " ", piece).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(piece)
    return " ".join(deduped)


def sanitize_chat_output(text: Any, *, max_sentences: int = 3, max_chars: int = 360) -> str:
    content = str(text or "").replace("\r\n", "\n").strip()
    if not content:
        return ""

    content = _extract_json_text(content)
    content = _CHAT_CODE_BLOCK_RE.sub("", content)

    kept_lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue
        if _looks_like_meta_line(line):
            continue
        if _CHAT_TABLE_LINE_RE.match(line) or _CHAT_TABLE_SEPARATOR_RE.match(line):
            continue
        if line.startswith("{") or line.startswith("["):
            continue
        kept_lines.append(line)

    paragraphs: list[str] = []
    for paragraph in re.split(r"\n{2,}", "\n".join(kept_lines).strip()):
        chunk = re.sub(r"\s+", " ", paragraph).strip()
        if not chunk:
            continue
        chunk = re.sub(
            r"^(tabii ki|elbette|şimdi size|simdi size|analiz ediyorum|öncelikle|oncelikle|kısaca|kisaca|sizin için|sizin icin)[,:;\-\s]+",
            "",
            chunk,
            flags=re.IGNORECASE,
        ).strip()
        if not chunk:
            continue
        cleaned = _dedupe_sentences(chunk)
        if cleaned:
            paragraphs.append(cleaned)
        if len(paragraphs) >= max_sentences:
            break

    output = "\n\n".join(paragraphs).strip()
    if not output:
        return ""
    if len(output) > max_chars:
        trimmed = output[:max_chars].rstrip()
        last_boundary = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
        if last_boundary >= int(max_chars * 0.6):
            trimmed = trimmed[: last_boundary + 1]
        output = trimmed.strip()
    return output


def chat_output_needs_retry(text: Any, *, sanitized_text: str | None = None) -> bool:
    raw = str(text or "").replace("\r\n", "\n").strip()
    clean = str(sanitized_text if sanitized_text is not None else sanitize_chat_output(raw)).strip()
    if not clean:
        return True
    if len(clean) > 420:
        return True
    if len(clean.splitlines()) > 3:
        return True
    low = raw.lower()
    if "```" in raw or _CHAT_CODE_BLOCK_RE.search(raw):
        return True
    if low.startswith("{") or low.startswith("["):
        return True
    if any(marker in low for marker in _CHAT_META_PREFIXES):
        return False
    if any(line.strip().startswith("|") and line.strip().endswith("|") for line in raw.splitlines()):
        return True
    if re.search(r"(?i)\b(deliverable spec|done criteria|success criteria|system note|sistem notu)\b", raw):
        return True
    return False


def filter_chat_history(history: list[Any] | None, *, max_pairs: int = 4) -> list[dict[str, str]]:
    if not isinstance(history, list) or not history:
        return []
    task_markers = (
        "deliverable spec",
        "done criteria",
        "success criteria",
        "system note",
        "sistem notu",
        "workflow",
        "pipeline",
        "critic",
        "verify",
        "task_id",
        "skeleton",
        "json",
        "```",
    )
    filtered: list[dict[str, str]] = []
    for item in history[-max_pairs:]:
        if not isinstance(item, dict):
            continue
        user_text = str(
            item.get("user_message")
            or item.get("user_input")
            or item.get("prompt")
            or item.get("content")
            or ""
        ).strip()
        bot_text = str(
            item.get("bot_response")
            or item.get("assistant_message")
            or item.get("response")
            or item.get("message")
            or ""
        ).strip()
        if not user_text and not bot_text:
            continue
        combined = f"{user_text}\n{bot_text}".lower()
        if any(marker in combined for marker in task_markers):
            continue
        user_clean = sanitize_chat_output(user_text, max_sentences=2, max_chars=180)
        bot_clean = sanitize_chat_output(bot_text, max_sentences=2, max_chars=180)
        if not user_clean or not bot_clean:
            continue
        filtered.append({"user_message": user_clean, "bot_response": bot_clean})
    return filtered


def build_chat_history_block(history: list[Any] | None, *, max_pairs: int = 4) -> str:
    rows = filter_chat_history(history, max_pairs=max_pairs)
    if not rows:
        return ""
    lines = ["Geçmiş konuşma:"]
    for row in rows:
        lines.append(f"Kullanıcı: {row['user_message']}")
        lines.append(f"Elyan: {row['bot_response']}")
    return "\n".join(lines).strip()


def build_chat_fallback_message(*, language: str = "tr") -> str:
    if str(language or "tr").strip().lower().startswith("en"):
        return "I'm here. Tell me what you need and I'll take it from there."
    return "Buradayım. Ne yapmak istediğini söyle, birlikte ilerleyelim."


def blocked_command_reason(user_input: str, *, tool_name: str = "") -> str:
    low = _normalize_text(user_input)
    tool = _normalize_text(tool_name)
    if not low:
        return ""

    runtime_tool = tool in _UI_TOOL_NAMES or tool in {
        "open_app",
        "open_url",
        "close_app",
        "run_command",
        "run_safe_command",
        "execute_command",
        "execute_shell_command",
    }

    command_like = runtime_tool or bool(
        re.search(
            r"\b("
            r"çöz|coz|solve|atla|skip|bypass|pass|handle|"
            r"çalıştır|calistir|run|execute|"
            r"aç|ac|kapat|başlat|baslat|"
            r"yaz|gir|enter|open|close|"
            r"tıkla|tikla|click|scroll|kaydır|kaydir|"
            r"sil|delete|remove|erase|wipe|format|geç|gec|"
            r"yönet|yonet"
            r")\b",
            low,
        )
    )

    if _contains_any(low, _CAPTCHA_MARKERS) and (
        command_like
        or any(marker in low for marker in ("geç", "gec", "atla", "skip", "bypass", "pass", "çöz", "coz", "solve", "enter"))
    ):
        return "CAPTCHA/2FA/OTP doğrulamalarını atlatamam."
    if _contains_any(low, _AUTH_MARKERS) and (
        command_like or any(marker in low for marker in ("oturum", "giriş", "giris", "login", "login ol", "log in", "sign in", "authenticate"))
    ):
        return "Oturum açma ve kimlik doğrulama adımlarını otomatik olarak geçemem."
    if command_like and _contains_any(low, _PRIVILEGE_MARKERS) and any(
        marker in low for marker in ("çalıştır", "calistir", "run", "execute", "komut", "command", "terminal", "shell", "bash")
    ):
        return "sudo/root gibi ayrıcalık gerektiren işlemleri çalıştırmam."
    if command_like and _contains_any(low, _DESTRUCTIVE_MARKERS):
        return "Toplu silme, format ya da wipe gibi yıkıcı işlemleri otomatik çalıştırmam."
    if command_like and _contains_any(low, _VOICE_MARKERS):
        return "Mikrofon/voice işlemleri bu akışta desteklenmiyor."
    if command_like and _contains_any(low, _INACCESSIBLE_UI_MARKERS):
        return "Görünmeyen veya erişilemeyen UI üzerinde güvenilir işlem yapamam."
    return ""


def requires_screen_state(tool_name: str) -> bool:
    return _normalize_text(tool_name) in _UI_TOOL_NAMES


def screen_state_is_actionable(screen_state: Any, *, minimum_confidence: float = 0.35) -> tuple[bool, str]:
    if screen_state is None:
        return False, "screen_state_missing"
    if hasattr(screen_state, "to_dict"):
        try:
            payload = dict(screen_state.to_dict())  # type: ignore[call-arg]
        except Exception:
            payload = {}
    elif isinstance(screen_state, dict):
        payload = dict(screen_state)
    else:
        payload = {}
    if not payload:
        return False, "screen_state_missing"

    confidence = float(payload.get("confidence") or 0.0)
    accessibility = payload.get("accessibility")
    if not isinstance(accessibility, list):
        accessibility = []
    ocr_text = str(payload.get("ocr_text") or "").strip()
    vision_summary = str(payload.get("vision_summary") or payload.get("summary") or "").strip()
    clipboard_text = str(payload.get("clipboard_text") or "").strip()
    cursor = payload.get("cursor") if isinstance(payload.get("cursor"), dict) else {}
    selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else {}
    source_counts = payload.get("source_counts") if isinstance(payload.get("source_counts"), dict) else {}

    has_structure = bool(accessibility or ocr_text or vision_summary or clipboard_text or cursor or selection or source_counts)
    if confidence < float(minimum_confidence or 0.0) and not has_structure:
        return False, f"screen_state_low_confidence:{confidence:.2f}"
    if not has_structure:
        return False, "screen_state_insufficient"
    return True, ""


@dataclass
class CommandRouteDecision:
    mode: str
    confidence: float
    reason: str
    family_scores: dict[str, float] = field(default_factory=dict)
    should_clarify: bool = False
    clarification_message: str = ""
    refusal: bool = False
    refusal_message: str = ""
    model_tier: str = "chat"
    should_bypass_pipeline: bool = False
    detected_families: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_markers(text: str, markers: tuple[str, ...], *, weight: float = 0.18, cap: float = 0.9) -> float:
    low = _normalize_text(text)
    hits = sum(1 for marker in markers if marker and marker in low)
    if not hits:
        return 0.0
    return min(cap, 0.25 + hits * weight)


def _looks_like_web_build_request(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    has_marker = any(marker in low for marker in _WEB_BUILD_MARKERS)
    has_verb = any(verb in low for verb in _WEB_BUILD_VERBS)
    if not has_marker:
        return False
    if has_verb:
        return True
    return any(phrase in low for phrase in ("html css js", "html/css/js", "frontend ui"))


def classify_command_route(
    user_input: str,
    *,
    quick_intent: Any = None,
    parsed_intent: dict[str, Any] | None = None,
    attachments: list[str] | None = None,
    capability_domain: str = "",
    screen_state: Any = None,
    metadata: dict[str, Any] | None = None,
) -> CommandRouteDecision:
    low = _normalize_text(user_input)
    meta = metadata if isinstance(metadata, dict) else {}
    attachment_list = [str(item or "").strip() for item in list(attachments or []) if str(item or "").strip()]
    category = str(getattr(quick_intent, "category", "") or "").strip().lower()
    quick_conf = float(getattr(quick_intent, "confidence", 0.0) or 0.0)
    parsed_action = str((parsed_intent or {}).get("action") or "").strip().lower() if isinstance(parsed_intent, dict) else ""
    route_hint = str((parsed_intent or {}).get("_route_to_llm") or "").strip().lower() if isinstance(parsed_intent, dict) else ""

    refusal_reason = blocked_command_reason(low, tool_name=str(meta.get("tool_name") or ""))
    if refusal_reason:
        return CommandRouteDecision(
            mode="communication",
            confidence=0.96,
            reason=refusal_reason,
            refusal=True,
            refusal_message=refusal_reason,
            model_tier="chat",
            should_bypass_pipeline=True,
        )

    family_scores: dict[str, float] = {
        "communication": 0.0,
        "screen": 0.0,
        "browser": 0.0,
        "file": 0.0,
        "research": 0.0,
        "code": 0.0,
        "task": 0.0,
    }

    if category in {"greeting", "chat"} or _contains_any(low, _GREETING_MARKERS):
        family_scores["communication"] = max(family_scores["communication"], 0.94 if category in {"greeting", "chat"} else 0.85)
    if category == "question" or _contains_any(low, _QUESTION_MARKERS):
        family_scores["communication"] = max(family_scores["communication"], 0.72)
    if category == "calculation":
        family_scores["communication"] = max(family_scores["communication"], 0.82)

    if parsed_action in {"chat", "show_help", "respond", "answer", "unknown", ""} or route_hint == "llm":
        family_scores["communication"] = max(family_scores["communication"], 0.78 if parsed_action in {"chat", "show_help", "respond", "answer"} else 0.55)

    family_scores["screen"] = max(
        family_scores["screen"],
        _score_markers(low, _SCREEN_MARKERS, weight=0.13, cap=0.9),
    )
    family_scores["browser"] = max(
        family_scores["browser"],
        _score_markers(low, _BROWSER_MARKERS, weight=0.15, cap=0.92),
    )
    family_scores["file"] = max(
        family_scores["file"],
        _score_markers(low, _FILE_MARKERS, weight=0.16, cap=0.92),
    )
    family_scores["research"] = max(
        family_scores["research"],
        _score_markers(low, _RESEARCH_MARKERS, weight=0.17, cap=0.96),
    )
    family_scores["code"] = max(
        family_scores["code"],
        _score_markers(low, _CODE_MARKERS, weight=0.16, cap=0.94),
    )
    if _looks_like_web_build_request(low):
        family_scores["code"] = max(family_scores["code"], 0.88)

    task_score = 0.0
    if _contains_any(low, _TASK_MARKERS):
        task_score += 0.4
    if any(token in low for token in ("ve sonra", "ardından", "ardindan", "sonra", "then", "after that", "sırasıyla", "sirayla")):
        task_score += 0.2
    if any(token in low for token in ("aç", "ac", "kapat", "başlat", "baslat", "odaklan", "focus", "open", "close")):
        task_score += 0.15
    family_scores["task"] = min(0.95, task_score)

    if attachment_list:
        image_like = any(str(path).lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")) for path in attachment_list)
        if image_like:
            family_scores["screen"] = max(family_scores["screen"], 0.65)
        else:
            family_scores["file"] = max(family_scores["file"], 0.48)

    capability = str(capability_domain or "").strip().lower()
    if capability in {"screen_operator", "desktop_control", "screen"}:
        family_scores["screen"] = max(family_scores["screen"], 0.82)
    elif capability == "browser":
        family_scores["browser"] = max(family_scores["browser"], 0.82)
    elif capability == "file":
        family_scores["file"] = max(family_scores["file"], 0.82)
    elif capability == "research":
        family_scores["research"] = max(family_scores["research"], 0.82)
    elif capability == "code":
        family_scores["code"] = max(family_scores["code"], 0.82)

    if "http://" in low or "https://" in low or "www." in low:
        family_scores["browser"] = max(family_scores["browser"], 0.84)

    if screen_state is not None:
        ok, _ = screen_state_is_actionable(screen_state)
        if ok:
            family_scores["screen"] = max(family_scores["screen"], 0.48)

    if quick_conf:
        if category in {"greeting", "chat"}:
            family_scores["communication"] = max(family_scores["communication"], min(0.98, quick_conf + 0.05))
        elif category == "question":
            family_scores["communication"] = max(family_scores["communication"], min(0.9, quick_conf + 0.02))
        elif category == "research":
            family_scores["research"] = max(family_scores["research"], min(0.96, quick_conf + 0.05))
        elif category == "coding":
            family_scores["code"] = max(family_scores["code"], min(0.94, quick_conf + 0.05))
        elif category == "file_operation":
            family_scores["file"] = max(family_scores["file"], min(0.94, quick_conf + 0.05))
        elif category == "command":
            family_scores["task"] = max(family_scores["task"], min(0.9, quick_conf + 0.02))

    sorted_families = sorted(family_scores.items(), key=lambda item: item[1], reverse=True)
    best_mode, best_score = sorted_families[0]
    second_mode, second_score = sorted_families[1] if len(sorted_families) > 1 else ("", 0.0)
    active_families = [mode for mode, score in sorted_families if score >= 0.35]

    if best_score <= 0.0:
        if category in {"greeting", "chat", "question"} or _contains_any(low, _GREETING_MARKERS + _QUESTION_MARKERS):
            return CommandRouteDecision(
                mode="communication",
                confidence=0.68,
                reason="chat_like_default",
                family_scores=family_scores,
                should_bypass_pipeline=True,
                model_tier="chat",
            )
        return CommandRouteDecision(
            mode="task",
            confidence=0.45,
            reason="fallback_task_route",
            family_scores=family_scores,
            should_clarify=True,
            clarification_message="Komutu netleştirmem gerekiyor. Tek cümlede hedefini yazabilir misin?",
            model_tier="inference",
        )

    if len(active_families) > 1:
        # Explicit multi-family requests should clarify rather than guess.
        family_labels = {
            "screen": "ekran",
            "browser": "tarayıcı",
            "file": "dosya",
            "research": "araştırma",
            "code": "kod",
            "task": "genel görev",
            "communication": "sohbet",
        }
        detected = [family_labels.get(mode, mode) for mode in active_families[:3]]
        clarification = (
            "Komut birden fazla hedef içeriyor: "
            + ", ".join(detected)
            + ". Tek bir hedef seç ya da sırayla ayır."
        )
        if best_mode == "communication" and best_score >= 0.78 and second_score < 0.35:
            pass
        else:
            return CommandRouteDecision(
                mode=best_mode if best_mode in family_scores else "task",
                confidence=float(min(0.99, best_score)),
                reason="multi_family_ambiguous",
                family_scores=family_scores,
                should_clarify=True,
                clarification_message=clarification,
                model_tier="reasoning" if best_mode in {"research", "code"} else "inference",
                detected_families=active_families,
            )

    if best_mode == "communication":
        if best_score >= 0.6 and second_score < 0.35:
            return CommandRouteDecision(
                mode="communication",
                confidence=float(min(0.99, best_score)),
                reason="communication_route",
                family_scores=family_scores,
                should_bypass_pipeline=True,
                model_tier="chat",
            )
        return CommandRouteDecision(
            mode="communication",
            confidence=float(min(0.9, best_score)),
            reason="communication_clarify",
            family_scores=family_scores,
            should_clarify=True,
            clarification_message="Sohbet mi, yoksa bir araç/iş akışı mı istediğini netleştirir misin?",
            should_bypass_pipeline=True,
            model_tier="chat",
        )

    if best_mode in {"research", "code"}:
        if best_score >= 0.62 and (best_score - second_score) >= 0.15:
            return CommandRouteDecision(
                mode=best_mode,
                confidence=float(min(0.99, best_score)),
                reason=f"{best_mode}_route",
                family_scores=family_scores,
                model_tier="reasoning",
            )
        return CommandRouteDecision(
            mode=best_mode,
            confidence=float(min(0.9, best_score)),
            reason=f"{best_mode}_clarify",
            family_scores=family_scores,
            should_clarify=True,
            clarification_message="Görevi netleştirir misin? Hedef, çıktı ve varsa dosya yolunu tek cümlede yaz.",
            model_tier="reasoning",
        )

    if best_score >= 0.58 and (best_score - second_score) >= 0.18:
        model_tier = "inference"
        if best_mode == "screen":
            model_tier = "inference"
        elif best_mode == "browser":
            model_tier = "inference"
        elif best_mode == "file":
            model_tier = "inference"
        elif best_mode == "task":
            model_tier = "inference"
        return CommandRouteDecision(
            mode=best_mode,
            confidence=float(min(0.99, best_score)),
            reason=f"{best_mode}_route",
            family_scores=family_scores,
            model_tier=model_tier,
            detected_families=active_families,
        )

    if best_score >= 0.4:
        clarification = "Komutu netleştirmem gerekiyor. Hangi işlemi önceliklendireyim?"
        if best_mode in {"screen", "browser", "file", "task"}:
            clarification = (
                "Komut birkaç yöne gidiyor. Tek bir hedef seç: ekran, tarayıcı, dosya, araştırma ya da kod."
            )
        return CommandRouteDecision(
            mode=best_mode,
            confidence=float(min(0.85, best_score)),
            reason="low_confidence_clarify",
            family_scores=family_scores,
            should_clarify=True,
            clarification_message=clarification,
            model_tier="reasoning" if best_mode in {"research", "code"} else "inference",
            detected_families=active_families,
        )

    return CommandRouteDecision(
        mode=best_mode,
        confidence=float(min(0.75, best_score)),
        reason="conservative_clarify",
        family_scores=family_scores,
        should_clarify=True,
        clarification_message="Komutu netleştirmem gerekiyor. Tek cümlede hedefini yazabilir misin?",
        model_tier="inference",
        detected_families=active_families,
    )


__all__ = [
    "CommandRouteDecision",
    "blocked_command_reason",
    "build_chat_fallback_message",
    "build_chat_history_block",
    "chat_output_needs_retry",
    "classify_command_route",
    "filter_chat_history",
    "requires_screen_state",
    "sanitize_chat_output",
    "screen_state_is_actionable",
]
