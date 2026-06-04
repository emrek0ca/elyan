from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class RoutedTask:
    tool_name: str
    args: dict[str, Any]
    reason: str
    intent: str = ""
    confidence: float = 1.0
    requires_confirmation: bool = False
    is_multi_step: bool = False
    privacy_class: str = "public_text"
    plan_preview: dict[str, Any] | None = None
    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)


TR_WEEKDAY_INDEX = {
    "pazartesi": 0,
    "sali": 1,
    "salı": 1,
    "carsamba": 2,
    "çarşamba": 2,
    "persembe": 3,
    "perşembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
TR_WEEKDAY_LABELS = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar",
}


def _normalise(text: str) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("ı", "i")
    value = value.replace("ğ", "g").replace("ü", "u").replace("ş", "s")
    value = value.replace("ö", "o").replace("ç", "c")
    return " ".join(value.split())


def _strip_polite_suffix(value: str) -> str:
    value = value.strip(" .,!?:;")
    value = re.sub(
        r"\b(lutfen|please|acabilir misin|acar misin|acarmisin|gosterir misin|bakabilir misin|anlatir misin)\b",
        "",
        value,
    ).strip()
    return value.strip(" .,!?:;")


def _strip_leading_fillers(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(
        r"^(?:da|de|te|ta|ile|icin|için|hakkinda|hakkında|about|for|the|bir|bu|su|şu|lutfen|lütfen|please)\b[\s,.:;!?-]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .,!?:;")


def _clean_app_name(value: str) -> str:
    cleaned = _strip_polite_suffix(value)
    cleaned = _strip_leading_fillers(cleaned)
    cleaned = re.sub(r"[’'](?:i|ı|u|ü|yi|yı|yu|yü)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .,!?:;\"'’")


def _is_generic_app_target(value: str) -> bool:
    normalized = _normalise(value)
    return normalized in {
        "",
        "app",
        "application",
        "program",
        "onu",
        "bunu",
        "o",
        "bu",
        "uygulama",
        "uygulamayi",
        "pencere",
        "window",
    }


def _looks_like_url(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    return bool(parsed.netloc and "." in parsed.netloc)


def _sys_info_query(text: str) -> str | None:
    q = _normalise(text)
    tokens = set(q.split())
    if tokens.intersection({"pil", "battery", "sarj"}):
        return "battery"
    if tokens.intersection({"cpu", "islemci"}):
        return "cpu"
    if tokens.intersection({"ram", "bellek", "memory"}):
        return "ram"
    if tokens.intersection({"disk", "depolama", "storage"}):
        return "disk"
    if tokens.intersection({"ag", "wifi", "network", "internet"}):
        return "network"
    if tokens.intersection({"saat", "time", "zaman"}):
        return "time"
    if tokens.intersection({"tarih", "date"}) or "bugun hangi gun" in q:
        return "date"
    if q in {"sistem bilgisi", "system info", "sistem durumu"}:
        return "all"
    return None


def _date_query(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("yarin", "tomorrow")):
        return "tomorrow"
    if any(token in q for token in ("siradaki", "sonraki", "next")):
        return "next"
    if any(token in q for token in ("hafta", "week")):
        return "upcoming"
    if any(token in q for token in ("ay", "month")):
        return "this month"
    return "today" if any(token in q for token in ("bugun", "today")) else "agenda"


def _extract_after(patterns: list[str], text: str) -> str:
    original = str(text or "").strip()
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return _strip_polite_suffix(match.group(1))
    return ""


def _workspace_root() -> Path:
    return Path.cwd().resolve()


def _slugify_output_hint(value: str, fallback: str) -> str:
    cleaned = _normalise(value)
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:64] or fallback


def _default_output_path(extension: str, hint: str) -> str:
    filename = f"{_slugify_output_hint(hint, 'elyan-output')}{extension}"
    return str((_workspace_root() / "elyan_output" / filename).resolve())


def _resolve_output_path(text: str, extension: str, *, hint: str) -> str:
    explicit = re.search(r'["“](.+?)["”]', text)
    if explicit:
        candidate = Path(explicit.group(1).strip()).expanduser()
        if not candidate.suffix:
            candidate = candidate.with_suffix(extension)
        if not candidate.is_absolute():
            candidate = (_workspace_root() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return str(candidate)
    absolute = re.search(
        rf"((?:/|~)[^\s]+(?:{re.escape(extension.lstrip('.'))}))",
        text,
        flags=re.IGNORECASE,
    )
    if absolute:
        return str(Path(absolute.group(1).strip()).expanduser().resolve())
    relative = re.search(
        rf"([A-Za-z0-9_\-./]+(?:{re.escape(extension.lstrip('.'))}))",
        text,
        flags=re.IGNORECASE,
    )
    if relative:
        return str((_workspace_root() / relative.group(1).strip()).resolve())
    return _default_output_path(extension, hint)


_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".json", ".csv", ".rtf", ".html", ".htm"}
_DATA_SUFFIXES = {".csv", ".json"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_OCR_SUFFIXES = _IMAGE_SUFFIXES | {".pdf"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".webm"}


def _selected_artifact_items(selected_artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(selected_artifacts, list):
        return []
    return [item for item in selected_artifacts if isinstance(item, dict)]


def _resolve_candidate_path(raw: str) -> str:
    candidate = Path(str(raw or "").strip()).expanduser()
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((_workspace_root() / candidate).resolve())


def _explicit_path_for_suffixes(text: str, allowed_suffixes: set[str]) -> str:
    original = str(text or "").strip()
    if not original:
        return ""
    quoted = re.search(r'["“](.+?)["”]', original)
    if quoted:
        candidate = quoted.group(1).strip()
        if Path(candidate).suffix.lower() in allowed_suffixes:
            return _resolve_candidate_path(candidate)
    for match in re.finditer(
        r"([A-Za-z]:[\\/][^\s\"“”]+|(?:~|/)[^\s\"“”]+|[A-Za-z0-9_.\\/-]+\.[A-Za-z0-9]+)",
        original,
        flags=re.IGNORECASE,
    ):
        candidate = match.group(1).strip(" ,;:()[]{}")
        if Path(candidate).suffix.lower() in allowed_suffixes:
            return _resolve_candidate_path(candidate)
    return ""


def _selected_paths_for(path: str, selected_artifacts: list[dict[str, Any]] | None) -> list[str]:
    normalized_path = str(path or "").strip().lower()
    if not normalized_path:
        return []
    for item in _selected_artifact_items(selected_artifacts):
        candidate = str(item.get("path", "") or "").strip()
        if candidate and candidate.lower() == normalized_path:
            return [candidate]
    return []


def _selected_artifact_path(
    selected_artifacts: list[dict[str, Any]] | None,
    *,
    kinds: set[str] | None = None,
    suffixes: set[str] | None = None,
) -> str:
    normalized_kinds = {str(kind).strip().lower() for kind in (kinds or set()) if str(kind).strip()}
    allowed_suffixes = {str(suffix).strip().lower() for suffix in (suffixes or set()) if str(suffix).strip()}
    for item in _selected_artifact_items(selected_artifacts):
        candidate = str(item.get("path", "") or "").strip()
        if not candidate:
            continue
        kind = str(item.get("kind", "") or "").strip().lower()
        suffix = Path(candidate).suffix.lower()
        kind_ok = not normalized_kinds or kind in normalized_kinds
        suffix_ok = not allowed_suffixes or suffix in allowed_suffixes
        if kind_ok and suffix_ok:
            return candidate
    return ""


def _resolve_document_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DOCUMENT_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_data_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _DATA_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_ocr_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _OCR_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"image", "document"},
        suffixes=_OCR_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_audio_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _AUDIO_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"audio"},
        suffixes=_AUDIO_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_image_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _IMAGE_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"image"},
        suffixes=_IMAGE_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _document_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("ozetle", "özetle", "summary", "summarize")):
        return "summary"
    if any(token in q for token in ("madde", "bullet", "listele", "sirala", "sırala")):
        return "bullets"
    return "read"


def _ocr_mode(text: str) -> str:
    return _document_mode(text)


def _image_read_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("palette", "palet", "renk")):
        return "palette"
    if any(
        token in q
        for token in (
            "metadata",
            "meta",
            "boyut",
            "cozunurluk",
            "çözünürlük",
            "resolution",
        )
    ):
        return "metadata"
    return "summary"


def _data_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("preview", "onizleme", "önizleme", "ilk satir", "ilk satır")):
        return "preview"
    if any(token in q for token in ("profil", "profile", "istatistik")):
        return "profile"
    return "summary"


def _chart_type(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("histogram", "dagilim", "dağılım")):
        return "histogram"
    if any(token in q for token in ("scatter", "daginik", "dağınık")):
        return "scatter"
    if any(token in q for token in ("line", "cizgi", "çizgi")):
        return "line"
    return "bar"


def _latex_parse_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("normalize", "normalizasyon", "normallestir", "normallestir", "normalize et")):
        return "normalize"
    return "parse"


def _math_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("carpanlara ayir", "çarpanlara ayır", "factor")):
        return "factor"
    if any(token in q for token in ("sadelestir", "sadeleştir", "simplify")):
        return "simplify"
    if any(token in q for token in ("genislet", "genişlet", "expand")):
        return "expand"
    if any(token in q for token in ("hesapla", "evaluate", "sayisal", "sayısal")):
        return "evaluate"
    return "solve"


def _is_probably_latex_expression(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    return candidate.startswith(("\\", "$")) or any(
        token in candidate for token in ("\\frac", "\\sqrt", "\\sum", "\\int", "\\alpha", "\\beta", "{", "}")
    )


def _spoken_text_payload(text: str) -> str:
    original = str(text or "").strip()
    quoted = re.search(r'["“](.+?)["”]', original)
    if quoted:
        return quoted.group(1).strip()
    cleaned = re.sub(r"\b(?:sesli|yüksek sesle|yuksek sesle)\b", " ", original, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:oku|okur musun|okuyabilir misin|read aloud|speak)\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" .,!?:;")


def _extract_math_expression(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+denklemini\s+(?:coz|çöz|solve)$",
        r"(.+?)\s+(?:i|ı|yi|yı|yu|yü)['’]?(?:\s+)?carpanlara\s+ayir$",
        r"(.+?)\s+(?:i|ı|yi|yı|yu|yü)['’]?(?:\s+)?çarpanlara\s+ayır$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:sadelestir|sadeleştir|simplify)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:genislet|genişlet|expand)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:hesapla|evaluate)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return original.strip(" .,!?:;")


def _extract_latex_expression(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+(?:ifadesini\s+)?(?:parse et|normalize et|normallestir|normallestir)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:coz|çöz|solve|sadelestir|sadeleştir|carpanlara ayir|çarpanlara ayır|factor|genislet|genişlet|expand|hesapla|evaluate)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return original.strip(" .,!?:;")


def _schedule_reference_datetime(text: str) -> dt.datetime | None:
    q = _normalise(text)
    now = dt.datetime.now().replace(second=0, microsecond=0)

    target_date = now.date()
    if "yarin" in q or "tomorrow" in q:
        target_date = now.date() + dt.timedelta(days=1)
    elif "bugun" in q or "today" in q:
        target_date = now.date()
    else:
        for token, weekday in TR_WEEKDAY_INDEX.items():
            if token in q:
                delta = (weekday - now.weekday()) % 7
                if delta == 0:
                    delta = 7
                target_date = now.date() + dt.timedelta(days=delta)
                break

    hour = 9
    minute = 0
    time_match = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(?:te|ta|de|da)?\b", q)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
    elif "sabah" in q:
        hour = 9
    elif any(token in q for token in ("ogle", "öğle", "noon")):
        hour = 12
    elif any(token in q for token in ("aksam", "akşam", "evening")):
        hour = 18

    try:
        return dt.datetime.combine(target_date, dt.time(hour=hour, minute=minute))
    except ValueError:
        return None


def _has_explicit_schedule_day(text: str) -> bool:
    q = _normalise(text)
    if any(token in q for token in ("yarin", "tomorrow", "bugun", "today")):
        return True
    return any(token in q for token in TR_WEEKDAY_INDEX)


def _strip_schedule_tokens(text: str) -> str:
    cleaned = str(text or "").strip()
    patterns = [
        r"\b(?:yarin|tomorrow|bugun|today|sabah|ogle|öğle|aksam|akşam|gece)\b",
        r"\b(?:pazartesi|sali|salı|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:te|ta|de|da)?\b",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:takvime|reminder|hatirlatici|hatırlatıcı|ekle|olustur|oluştur)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bdiye\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" .,!?:;")


def _build_plan_summary(summary: str, steps: list[dict[str, Any]], privacy_class: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "steps": steps,
        "privacyClass": privacy_class,
    }


def _day_time_label(value: dt.datetime) -> str:
    return f"{TR_WEEKDAY_LABELS.get(value.weekday(), value.strftime('%A'))} {value.strftime('%H:%M')}"


def revise_plan_payload(plan: dict[str, Any], revision_text: str) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    normalized = _normalise(revision_text)
    if not normalized:
        return None

    capability = str(plan.get("capability", "") or "").strip()
    steps = plan.get("steps", [])
    steps = [dict(step) for step in steps if isinstance(step, dict)]
    if not steps:
        return None

    if capability in {"add_calendar_event", "add_reminder"}:
        schedule_match = _schedule_reference_datetime(revision_text)
        current_args = dict(steps[0].get("args", {}) or {})
        if "bir saat" in normalized and any(token in normalized for token in ("ertele", "later", "sonra")):
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed + dt.timedelta(hours=1)
                except ValueError:
                    schedule_match = None
        elif "yarina al" in normalized or "yarına al" in revision_text.lower():
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed + dt.timedelta(days=1)
                except ValueError:
                    schedule_match = None
        elif schedule_match is not None and not _has_explicit_schedule_day(revision_text):
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed.replace(
                        hour=schedule_match.hour,
                        minute=schedule_match.minute,
                    )
                except ValueError:
                    pass
        if schedule_match is None:
            return None

        title = str(current_args.get("title", "") or "Yeni görev")
        if capability == "add_calendar_event":
            current_args["start_iso"] = schedule_match.isoformat()
            current_args["end_iso"] = (schedule_match + dt.timedelta(hours=1)).isoformat()
            steps[0]["description"] = f"Takvime '{title}' etkinliği eklenecek."
            summary = f"Takvime {_day_time_label(schedule_match)} için '{title}' etkinliğini ekleyeceğim."
        else:
            current_args["due_iso"] = schedule_match.isoformat()
            steps[0]["description"] = f"'{title}' hatırlatıcısı oluşturulacak."
            summary = f"'{title}' için {_day_time_label(schedule_match)} zamanlı bir hatırlatıcı oluşturacağım."
        steps[0]["args"] = current_args
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(summary, steps, "local_private"),
        }

    if capability == "open_app":
        replacement = _clean_app_name(
            _extract_after(
                [
                    r"(.+?)\s+yerine\s+(.+?)\s+(?:ac|aç|open|launch)$",
                    r"(.+?)\s+yap$",
                ],
                revision_text,
            ) or revision_text
        )
        if not replacement or _is_generic_app_target(replacement):
            return None
        steps[0]["args"] = {"app_name": replacement}
        steps[0]["description"] = f"{replacement} açılacak."
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(f"Önce {replacement} açılacak.", steps, "local_private"),
        }

    if capability == "browser_control":
        replacement = _extract_after(
            [
                r"(.+?)\s+yerine\s+(.+?)\s+(?:ac|aç|open|launch)$",
                r"(.+?)\s+yap$",
            ],
            revision_text,
        ) or revision_text
        replacement_url = _site_target_to_url(replacement)
        if not replacement_url:
            return None
        steps[0]["args"] = {"action": "open_url", "url": replacement_url}
        steps[0]["description"] = f"{replacement_url} açılacak."
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(f"{replacement_url} adresi açılacak.", steps, "public_text"),
        }

    if len(steps) >= 2 and str(steps[0].get("capability", "") or "") == "open_app" and str(
        steps[1].get("capability", "") or ""
    ) == "browser_control":
        replacement = _extract_after(
            [
                r".+?\s+yerine\s+(.+?)\s+(?:sitesini\s+)?(?:ac|aç|open|launch)$",
                r"(.+?)\s+yap$",
            ],
            revision_text,
        ) or revision_text
        replacement_url = _site_target_to_url(replacement)
        if not replacement_url:
            return None
        steps[1]["args"] = {"action": "open_url", "url": replacement_url}
        steps[1]["description"] = f"{replacement_url} açılacak."
        first_target = str(steps[0].get("args", {}).get("app_name", "") or "uygulama")
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(
                f"Önce {first_target} açılacak, ardından {replacement_url} adresi yüklenecek.",
                steps,
                "local_private",
            ),
        }

    return None


def _site_target_to_url(value: str) -> str | None:
    cleaned = _clean_app_name(value)
    if not cleaned:
        return None
    if _looks_like_url(cleaned):
        return cleaned if "://" in cleaned else f"https://{cleaned}"
    normalized = _normalise(cleaned)
    known = {
        "openai": "https://openai.com",
        "github": "https://github.com",
        "google": "https://google.com",
        "youtube": "https://youtube.com",
        "notion": "https://notion.so",
        "slack": "https://slack.com",
    }
    if normalized in known:
        return known[normalized]
    if normalized.endswith(" sitesi") or normalized.endswith(" sitesi ac"):
        normalized = normalized.replace(" sitesi", "").strip()
    slug = re.sub(r"[^a-z0-9]+", "", normalized)
    if slug:
        return f"https://{slug}.com"
    return None


def _calendar_add_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if "takvime" not in q or not any(token in q for token in ("ekle", "olustur", "oluştur")):
        return None
    when = _schedule_reference_datetime(q)
    if when is None:
        return None
    title = _strip_schedule_tokens(_extract_after([r"takvime\s+(.+?)\s+(?:ekle|olustur|oluştur)$"], original) or original)
    if not title:
        title = "Yeni etkinlik"
    end = when + dt.timedelta(hours=1)
    steps = [
        {
            "capability": "add_calendar_event",
            "description": f"Takvime '{title}' etkinliği eklenecek.",
        }
    ]
    summary = f"Takvime {_day_time_label(when)} için '{title}' etkinliğini ekleyeceğim."
    return RoutedTask(
        "add_calendar_event",
        {
            "title": title,
            "start_iso": when.isoformat(),
            "end_iso": end.isoformat(),
        },
        "calendar_add",
        intent="calendar_add",
        confidence=0.88,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
    )


def _reminder_add_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in ("hatirlatici", "hatırlatıcı", "reminder")) or not any(
        token in q for token in ("ekle", "olustur", "oluştur", "kur")
    ):
        return None
    when = _schedule_reference_datetime(q)
    if when is None:
        return None
    title_match = re.search(r"(.+?)\s+diye\s+(?:hatirlatici|hatırlatıcı|reminder)", original, flags=re.IGNORECASE)
    title = _strip_schedule_tokens(title_match.group(1) if title_match else original)
    if not title:
        title = "Yeni hatırlatıcı"
    steps = [
        {
            "capability": "add_reminder",
            "description": f"'{title}' hatırlatıcısı oluşturulacak.",
        }
    ]
    summary = f"'{title}' için {_day_time_label(when)} zamanlı bir hatırlatıcı oluşturacağım."
    return RoutedTask(
        "add_reminder",
        {
            "title": title,
            "due_iso": when.isoformat(),
        },
        "reminder_add",
        intent="reminder_add",
        confidence=0.9,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
    )


def _workspace_reminders_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if "hafta" in q and any(token in q for token in ("yapilacak", "yapılacak", "todo", "reminder", "hatirlat")):
        return RoutedTask(
            "get_reminders",
            {"query": "upcoming", "limit": 12},
            "reminders_week",
            intent="reminders_read",
            confidence=0.84,
            privacy_class="local_private",
        )
    return None


def _document_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_document = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DOCUMENT_SUFFIXES,
    )
    if not selected_document and not any(
        token in q for token in ("dosya", "belge", "pdf", "docx", "markdown", "json", "csv", "txt")
    ):
        return None
    if not any(token in q for token in ("oku", "ozetle", "özetle", "cikar", "çıkar", "listele", "maddeler")):
        return None
    path, selected_paths = _resolve_document_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _document_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "document_read",
        args,
        "document_read",
        intent="document_read",
        confidence=0.82,
        privacy_class="local_private",
    )


def _speech_transcription_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_audio = _selected_artifact_path(
        selected_artifacts,
        kinds={"audio"},
        suffixes=_AUDIO_SUFFIXES,
    )
    if not selected_audio and not any(
        token in q
        for token in (
            "transkript",
            "transcribe",
            "yaziya cevir",
            "yazıya çevir",
            "metne cevir",
            "metne çevir",
            "ses kaydi",
            "ses kaydı",
            "audio",
        )
    ):
        return None
    path, selected_paths = _resolve_audio_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"audioPath": path, "languageHint": "tr"}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "speech_to_text",
        args,
        "speech_to_text",
        intent="speech_to_text",
        confidence=0.84,
        privacy_class="local_private",
    )


def _text_to_speech_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("sesli oku", "yüksek sesle oku", "yuksek sesle oku", "read aloud")):
        return None
    payload = _spoken_text_payload(text)
    if not payload:
        return None
    return RoutedTask(
        "text_to_speech",
        {"text": payload, "languageHint": "tr", "interrupt": True},
        "text_to_speech",
        intent="text_to_speech",
        confidence=0.82,
        privacy_class="public_text",
    )


def _ocr_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_visual = _selected_artifact_path(
        selected_artifacts,
        kinds={"image", "document"},
        suffixes=_OCR_SUFFIXES,
    )
    if not selected_visual and not any(
        token in q for token in ("gorsel", "görsel", "ocr", "resim", "fotograf", "fotoğraf", "png", "jpg", "jpeg", "pdf")
    ):
        return None
    if not any(token in q for token in ("yazi", "yazı", "metin", "oku", "cikar", "çıkar", "ocr")):
        return None
    path, selected_paths = _resolve_ocr_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _ocr_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "ocr_read",
        args,
        "ocr_read",
        intent="ocr_read",
        confidence=0.8,
        privacy_class="local_private",
    )


def _image_read_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_image = _selected_artifact_path(
        selected_artifacts,
        kinds={"image"},
        suffixes=_IMAGE_SUFFIXES,
    )
    if not selected_image and not any(
        token in q
        for token in ("gorsel", "görsel", "resim", "fotograf", "fotoğraf", "image", "png", "jpg", "jpeg", "gif", "webp")
    ):
        return None
    if not any(
        token in q
        for token in ("incele", "ozetle", "özetle", "metadata", "meta", "boyut", "cozunurluk", "çözünürlük", "palette", "palet", "renk")
    ):
        return None
    path, selected_paths = _resolve_image_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _image_read_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "image_read",
        args,
        "image_read",
        intent="image_read",
        confidence=0.81,
        privacy_class="local_private",
    )


def _data_analyze_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_data = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    if not selected_data and not any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")):
        return None
    if not any(token in q for token in ("analiz", "incele", "profil", "istatistik", "preview", "onizleme", "önizleme")):
        return None
    path, selected_paths = _resolve_data_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _data_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "data_analyze",
        args,
        "data_analyze",
        intent="data_analyze",
        confidence=0.84,
        privacy_class="local_private",
    )


def _chart_generate_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_data = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    if not selected_data and not any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")):
        return None
    if not any(token in q for token in ("grafik", "chart", "histogram", "scatter", "bar", "line")):
        return None
    if not any(token in q for token in ("cikar", "çıkar", "uret", "üret", "olustur", "oluştur", "hazirla", "hazırla", "yap")):
        return None
    path, selected_paths = _resolve_data_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {
        "path": path,
        "chartType": _chart_type(text),
        "title": Path(path).stem,
    }
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "chart_generate",
        args,
        "chart_generate",
        intent="chart_generate",
        confidence=0.82,
        privacy_class="local_private",
    )


def _math_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("=", "^", "+", "-", "*", "/", "x", "denklem", "ifade")):
        return None
    if not any(
        token in q
        for token in ("coz", "çöz", "solve", "sadelestir", "sadeleştir", "carpanlara ayir", "çarpanlara ayır", "factor", "genislet", "genişlet", "expand", "hesapla", "evaluate")
    ):
        return None
    expression = _extract_math_expression(text)
    if not expression:
        return None
    args: dict[str, Any] = {"expression": expression, "mode": _math_mode(text)}
    if _is_probably_latex_expression(expression):
        args["_latexInput"] = _extract_latex_expression(text)
    return RoutedTask(
        "math_solve",
        args,
        "math_solve",
        intent="math_solve",
        confidence=0.86,
        privacy_class="public_text",
    )


def _latex_parse_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("latex", "parse", "normalize", "normallestir", "normalleştir")):
        return None
    expression = _extract_latex_expression(text)
    if not expression or not _is_probably_latex_expression(expression):
        return None
    return RoutedTask(
        "latex_parse",
        {"expression": expression, "mode": _latex_parse_mode(text)},
        "latex_parse",
        intent="latex_parse",
        confidence=0.84,
        privacy_class="public_text",
    )


def _document_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("docx", "word", "belge")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    output_path = _resolve_output_path(text, ".docx", hint=text or "elyan-document")
    steps = [
        {
            "capability": "document_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} DOCX dosyası oluşturulacak.",
        }
    ]
    return RoutedTask(
        "document_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "document_write",
        intent="document_write",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} DOCX dosyasını oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _spreadsheet_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("xlsx", "excel", "tablo", "cizelge", "çizelge", "sheet")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    output_path = _resolve_output_path(text, ".xlsx", hint=text or "elyan-sheet")
    steps = [
        {
            "capability": "spreadsheet_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} XLSX çalışma sayfası oluşturulacak.",
        }
    ]
    return RoutedTask(
        "spreadsheet_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "spreadsheet_write",
        intent="spreadsheet_write",
        confidence=0.83,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} XLSX çalışma sayfasını oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _presentation_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("pptx", "powerpoint", "sunum", "slide")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    output_path = _resolve_output_path(text, ".pptx", hint=text or "elyan-presentation")
    steps = [
        {
            "capability": "presentation_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} PPTX sunumu oluşturulacak.",
        }
    ]
    return RoutedTask(
        "presentation_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "presentation_write",
        intent="presentation_write",
        confidence=0.83,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} PPTX sunumunu oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _multi_step_browser_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if " ve " not in q or not any(token in q for token in (" ac", " aç", " open", " launch")):
        return None
    match = re.search(r"(.+?)\s+ve\s+(.+)$", original, flags=re.IGNORECASE)
    if not match:
        return None
    first, second = match.group(1).strip(), match.group(2).strip()
    if not any(token in _normalise(first) for token in ("ac", "aç", "open", "launch")):
        return None
    first_target = _clean_app_name(_extract_after([r"(.+?)\s+(?:ac|aç|open|launch)$"], first))
    second_target = _clean_app_name(_extract_after([r"(.+?)\s+(?:sitesini\s+)?(?:ac|aç|open|launch)$"], second))
    if not first_target or not second_target:
        return None
    url = _site_target_to_url(second_target)
    if not url:
        return None
    steps = [
        {"capability": "open_app", "args": {"app_name": first_target}, "description": f"{first_target} açılacak."},
        {"capability": "browser_control", "args": {"action": "open_url", "url": url}, "description": f"{url} açılacak."},
    ]
    summary = f"Önce {first_target} açılacak, ardından {url} adresi yüklenecek."
    return RoutedTask(
        "open_app",
        {"app_name": first_target},
        "multi_step_browser_open",
        intent="multi_step_browser_open",
        confidence=0.86,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _extract_email_addresses(text: str) -> list[str]:
    addresses = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", str(text or ""), flags=re.IGNORECASE)
    ordered: list[str] = []
    for address in addresses:
        candidate = address.strip()
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _research_topic(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+(?:hakk[ıi]nda|about)\s+(?:araştırma yap|arastirma yap|araştır|araştir|research|incele)$",
        r"(?:araştırma yap|arastirma yap|araştır|araştir|research|incele)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            candidate = _strip_leading_fillers(match.group(1))
            if candidate:
                return candidate
    return _strip_leading_fillers(original)


def _email_subject(topic: str, fallback: str) -> str:
    cleaned = _strip_leading_fillers(topic) or _strip_leading_fillers(fallback)
    if cleaned:
        return f"{cleaned[:80]} hakkında notlar"
    return "Hazırlanan e-posta"


def _build_web_research_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in ("araştır", "arastir", "araştırma", "research", "incele", "kaynak", "source", "verify")):
        return None
    if _extract_email_addresses(original) and any(token in q for token in ("mail", "email", "e-posta", "gönder", "gonder", "send")):
        return None

    topic = _research_topic(original)
    steps = [
        {
            "capability": "web_research",
            "args": {"query": topic},
            "description": f"{topic} hakkında web araştırması yapılacak.",
        }
    ]
    summary = f"'{topic}' hakkında güvenli web araştırması yapılacak."
    return RoutedTask(
        "web_research",
        {"query": topic},
        "web_research",
        intent="web_research",
        confidence=0.94,
        privacy_class="public_text",
        plan_preview=_build_plan_summary(summary, steps, "public_text"),
        steps=tuple(steps),
    )


def _build_email_draft_plan(
    *,
    recipients: list[str],
    topic: str,
    original: str,
    research_topic: str = "",
    research_query: str = "",
    include_send: bool = False,
) -> RoutedTask | None:
    if not recipients:
        return None
    subject = _email_subject(research_topic or topic, original)
    draft_args = {
        "to": recipients,
        "subject": subject,
        "topic": research_topic or topic or original,
        "prompt": original,
    }
    draft_step = {
        "capability": "email_draft",
        "args": draft_args,
        "description": f"{', '.join(recipients)} için e-posta taslağı hazırlanacak.",
    }
    steps: list[dict[str, Any]] = []
    summary_parts: list[str] = []
    if research_query:
        steps.append(
            {
                "capability": "web_research",
                "args": {"query": research_query},
                "description": f"{research_query} hakkında web araştırması yapılacak.",
            }
        )
        summary_parts.append(f"Önce {research_query} hakkında araştırma yapılacak")
    steps.append(draft_step)
    summary_parts.append(f"sonra {', '.join(recipients)} adresine taslak hazırlanacak")
    if include_send:
        steps.append(
            {
                "capability": "email_send",
                "args": {
                    "to": recipients,
                    "subject": subject,
                },
                "description": f"{', '.join(recipients)} adresine e-posta gönderilecek.",
            }
        )
        summary_parts.append("ve onaydan sonra e-posta gönderilecek")

    summary = "; ".join(summary_parts).strip().capitalize()
    return RoutedTask(
        "email_send" if include_send else "email_draft",
        draft_args,
        "email_draft",
        intent="email_send" if include_send else "email_draft",
        confidence=0.93 if include_send else 0.89,
        requires_confirmation=include_send,
        is_multi_step=include_send or bool(research_query),
        privacy_class="side_effect" if include_send else "public_text",
        plan_preview=_build_plan_summary(summary or "E-posta taslağı hazırlanacak.", steps, "side_effect" if include_send else "public_text"),
        steps=tuple(steps),
    )


def _email_send_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    recipients = _extract_email_addresses(original)
    if not recipients and not any(token in q for token in ("mail", "email", "e-posta")):
        return None
    if not any(token in q for token in ("gönder", "gonder", "yolla", "at", "send", "mail", "email")):
        return None
    research_query = ""
    if any(token in q for token in ("araştır", "arastir", "araştırma", "research", "incele", "kaynak", "source", "verify")):
        research_query = _research_topic(original)
    topic = research_query or _strip_leading_fillers(original)
    if not recipients:
        return None
    return _build_email_draft_plan(
        recipients=recipients,
        topic=topic,
        original=original,
        research_topic=topic,
        research_query=research_query,
        include_send=True,
    )


def _email_draft_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in ("taslak", "draft", "yaz", "hazırla", "hazirla", "compose")):
        return None
    recipients = _extract_email_addresses(original)
    if not recipients:
        return None
    topic = _research_topic(original)
    return _build_email_draft_plan(
        recipients=recipients,
        topic=topic,
        original=original,
        research_topic=topic,
        include_send=False,
    )


def artifact_target_clarification(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, str] | None:
    q = _normalise(text)
    data_requested = any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")) and any(
        token in q for token in ("analiz", "incele", "profil", "istatistik", "preview", "onizleme", "önizleme")
    )
    chart_requested = any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")) and any(
        token in q for token in ("grafik", "chart", "histogram", "scatter", "bar", "line")
    )
    document_requested = any(token in q for token in ("dosya", "belge", "pdf", "docx", "markdown", "json", "csv", "txt")) and any(
        token in q for token in ("oku", "ozetle", "özetle", "cikar", "çıkar", "listele", "maddeler")
    )
    ocr_requested = any(
        token in q for token in ("gorsel", "görsel", "ocr", "resim", "fotograf", "fotoğraf", "png", "jpg", "jpeg", "pdf")
    ) and any(token in q for token in ("yazi", "yazı", "metin", "oku", "cikar", "çıkar", "ocr"))
    audio_requested = any(
        token in q
        for token in (
            "transkript",
            "transcribe",
            "yaziya cevir",
            "yazıya çevir",
            "metne cevir",
            "metne çevir",
            "ses kaydi",
            "ses kaydı",
            "audio",
        )
    )
    image_requested = any(
        token in q for token in ("gorsel", "görsel", "resim", "fotograf", "fotoğraf", "image", "png", "jpg", "jpeg", "gif", "webp")
    ) and any(
        token in q
        for token in ("incele", "ozetle", "özetle", "metadata", "meta", "boyut", "cozunurluk", "çözünürlük", "palette", "palet", "renk")
    )

    if data_requested:
        path, _ = _resolve_data_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "data",
                "question": "Bu tablo için önce bir CSV/JSON dosyası seç veya çalışma alanındaki açık yolu yaz.",
            }
    if chart_requested:
        path, _ = _resolve_data_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "chart",
                "question": "Bu grafik için önce bir CSV/JSON dosyası seç veya çalışma alanındaki açık yolu yaz.",
            }
    if document_requested:
        path, _ = _resolve_document_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "document",
                "question": "Bu dosya için önce bir belge seç veya çalışma alanındaki açık yolu yaz.",
            }
    if ocr_requested:
        path, _ = _resolve_ocr_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "ocr",
                "question": "Bu görsel için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    if image_requested:
        path, _ = _resolve_image_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "image",
                "question": "Bu görsel için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    if audio_requested:
        path, _ = _resolve_audio_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "audio",
                "question": "Bu ses kaydı için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    return None


def route_text_to_tool(
    text: str,
    *,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> RoutedTask | None:
    original = str(text or "").strip()
    if not original:
        return None
    q = _normalise(original)

    calendar_add = _calendar_add_route(original)
    if calendar_add is not None:
        return calendar_add

    reminder_add = _reminder_add_route(original)
    if reminder_add is not None:
        return reminder_add

    multi_step = _multi_step_browser_route(original)
    if multi_step is not None:
        return multi_step

    speech_transcription = _speech_transcription_route(original, selected_artifacts)
    if speech_transcription is not None:
        return speech_transcription

    text_to_speech = _text_to_speech_route(original)
    if text_to_speech is not None:
        return text_to_speech

    data_analyze = _data_analyze_route(original, selected_artifacts)
    if data_analyze is not None:
        return data_analyze

    chart_generate = _chart_generate_route(original, selected_artifacts)
    if chart_generate is not None:
        return chart_generate

    document = _document_route(original, selected_artifacts)
    if document is not None:
        return document

    ocr = _ocr_route(original, selected_artifacts)
    if ocr is not None:
        return ocr

    image_read = _image_read_route(original, selected_artifacts)
    if image_read is not None:
        return image_read

    latex_parse = _latex_parse_route(original)
    if latex_parse is not None:
        return latex_parse

    math_route = _math_route(original)
    if math_route is not None:
        return math_route

    document_write = _document_write_route(original)
    if document_write is not None:
        return document_write

    spreadsheet_write = _spreadsheet_write_route(original)
    if spreadsheet_write is not None:
        return spreadsheet_write

    presentation_write = _presentation_write_route(original)
    if presentation_write is not None:
        return presentation_write

    email_send = _email_send_route(original)
    if email_send is not None:
        return email_send

    email_draft = _email_draft_route(original)
    if email_draft is not None:
        return email_draft

    web_research = _build_web_research_route(original)
    if web_research is not None:
        return web_research

    weekly_reminders = _workspace_reminders_route(original)
    if weekly_reminders is not None:
        return weekly_reminders

    if "youtube" in q and any(token in q for token in ("istatistik", "kanal", "son video", "buyume", "analytics")):
        return RoutedTask(
            "get_youtube_channel_report",
            {"query": original, "video_limit": 6},
            "youtube_report",
            intent="youtube_report",
            confidence=0.92,
        )

    if any(
        token in q
        for token in (
            "ekranda ne var",
            "ekrani analiz",
            "ekran analizi",
            "bu hatayi oku",
            "pencereyi analiz",
            "ne goruyorsun",
            "ekrana bak",
            "screen",
        )
    ):
        return RoutedTask(
            "analyze_screen",
            {"query": original, "target": "active_window"},
            "screen_analysis",
            intent="screen_analysis",
            confidence=0.94,
            privacy_class="local_private",
        )

    if any(token in q for token in ("dosya gezgini", "dosya yoneticisi", "dosya yöneticisi", "finder", "file explorer", "file manager")):
        if any(token in q for token in ("ac", "aç", "open", "launch", "başlat", "baslat", "start")):
            return RoutedTask("open_app", {"app_name": "Finder"}, "open_app", intent="open_app", confidence=0.98, privacy_class="local_private")

    sys_query = _sys_info_query(original)
    if sys_query:
        return RoutedTask("sys_info", {"query": sys_query}, "system_info", intent="system_info", confidence=0.98, privacy_class="local_private")

    if any(token in q for token in ("hava", "weather", "sicaklik", "yagmur")):
        location = _extract_after([r"(?:hava|weather|sicaklik|yagmur)\s+(?:durumu\s+)?(.+)$"], original)
        return RoutedTask("get_weather", {"location": location}, "weather", intent="weather", confidence=0.84)

    if any(token in q for token in ("takvim", "ajanda", "toplanti", "calendar")) and any(
        token in q
        for token in ("ne var", "goster", "kontrol", "oku", "siradaki", "bugun", "yarin", "week", "agenda", "bak")
    ):
        return RoutedTask(
            "get_calendar_events",
            {"query": _date_query(original), "limit": 8},
            "calendar_read",
            intent="calendar_read",
            confidence=0.9,
            privacy_class="local_private",
        )

    if any(token in q for token in ("animsatici", "hatirlatici", "reminder", "yapilacak")) and any(
        token in q for token in ("ne var", "goster", "kontrol", "oku", "bugun", "yarin", "upcoming", "bak")
    ):
        return RoutedTask(
            "get_reminders",
            {"query": _date_query(original), "limit": 8},
            "reminders_read",
            intent="reminders_read",
            confidence=0.9,
            privacy_class="local_private",
        )

    youtube_query = _extract_after(
        [
            r"youtube(?:['’]?(?:da|de)|\s+da|\s+de)?\s+(.+?)\s+(?:ac|aç|cal|çal|oynat|ara)$",
            r"(.+?)\s+youtube(?:['’]?(?:da|de)|\s+da|\s+de)?\s+(?:ac|aç|cal|çal|oynat)$",
        ],
        original,
    )
    if youtube_query:
        youtube_query = _strip_leading_fillers(youtube_query)
        return RoutedTask(
            "browser_control",
            {"action": "play_youtube", "query": youtube_query},
            "youtube_play",
            intent="youtube_play",
            confidence=0.95,
        )

    search_query = _extract_after(
        [
            r"(?:google(?:['’]?(?:da|de)|\s+da|\s+de)?|web(?:['’]?(?:de)|\s+de)?|internette)\s+(.+?)\s+(?:ara|search)$",
            r"(.+?)\s+(?:google(?:['’]?(?:da|de)|\s+da|\s+de)?|web(?:['’]?(?:de)|\s+de)?|internette)\s+(?:ara|search)$",
        ],
        original,
    )
    if search_query:
        search_query = _strip_leading_fillers(search_query)
        return RoutedTask(
            "browser_control",
            {"action": "search", "query": search_query},
            "web_search",
            intent="web_search",
            confidence=0.97,
        )

    close_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:kapat|close|quit|terminate|sonlandir|sonlandır|durdur)$",
            r"(?:kapat|close|quit|terminate|sonlandir|sonlandır|durdur)\s+(.+)$",
        ],
        original,
    )
    if close_target:
        close_target = _clean_app_name(close_target)
        if _is_generic_app_target(close_target):
            return RoutedTask("close_app", {"app_name": ""}, "close_active_app", intent="close_app", confidence=0.9, privacy_class="local_private")
        if close_target and not any(token in _normalise(close_target) for token in ("dosya", "file", "klasor", "folder")):
            return RoutedTask("close_app", {"app_name": close_target}, "close_app", intent="close_app", confidence=0.94, privacy_class="local_private")

    open_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:ac|aç|open|launch|başlat|baslat|start)$",
            r"(?:ac|aç|open|launch|başlat|baslat|start)\s+(.+)$",
        ],
        original,
    )
    if open_target:
        open_target = _clean_app_name(open_target)
        if _looks_like_url(open_target):
            return RoutedTask("browser_control", {"action": "open_url", "url": open_target}, "open_url", intent="open_url", confidence=0.93)
        if not _is_generic_app_target(open_target) and not any(token in _normalise(open_target) for token in ("dosya", "file", "klasor", "folder")):
            return RoutedTask("open_app", {"app_name": open_target}, "open_app", intent="open_app", confidence=0.95, privacy_class="local_private")

    command = _extract_after(
        [
            r"(?:terminalde|terminal|komut)\s+(.+?)\s+(?:calistir|çalıştır|run)$",
            r"(?:calistir|çalıştır|run)\s+(.+)$",
        ],
        original,
    )
    if command:
        summary = f"`{command}` komutu çalıştırılacak."
        steps = [
            {
                "capability": "shell_run",
                "args": {"command": command},
                "description": summary,
            }
        ]
        return RoutedTask(
            "shell_run",
            {"command": command},
            "shell_command",
            intent="shell_command",
            confidence=0.98,
            requires_confirmation=True,
            privacy_class="local_private",
            plan_preview=_build_plan_summary(summary, steps, "local_private"),
            steps=tuple(steps),
        )

    return None
