from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runtime.agent_planning import build_agent_plan


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


_TRAILING_CASE_TOKENS = {
    "i",
    "ı",
    "u",
    "ü",
    "yi",
    "yı",
    "yu",
    "yü",
    "ni",
    "nı",
    "nu",
    "nü",
}


def _strip_trailing_case_particles(value: str) -> str:
    tokens = [token for token in str(value or "").strip().split() if token]
    while tokens and _normalise(tokens[-1]) in _TRAILING_CASE_TOKENS:
        tokens.pop()
    return " ".join(tokens).strip()


def _clean_app_name(value: str) -> str:
    cleaned = _strip_polite_suffix(value)
    cleaned = _strip_leading_fillers(cleaned)
    cleaned = re.sub(r"[’'](?:i|ı|u|ü|yi|yı|yu|yü)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?i)(.{3,}?)(?:yi|yı|yu|yü|ni|nı|nu|nü)$", r"\1", cleaned)
    cleaned = _strip_trailing_case_particles(cleaned)
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


def _is_generic_window_reference(value: str) -> bool:
    normalized = _normalise(value)
    return normalized in {
        "",
        "onu",
        "bunu",
        "o",
        "bu",
        "buradaki",
        "aktif pencere",
        "bu pencere",
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
_DOCUMENT_SUMMARY_SAVE_TOKENS = {"ozetle", "özetle", "summary", "summarize"}
_DOCUMENT_SAVE_TOKENS = {"kaydet", "save", "sakla", "store"}


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


def _embedded_attachment_payload(text: str) -> tuple[str, list[str]]:
    original = str(text or "").strip()
    if not original:
        return "", []
    pattern = re.compile(
        r"---\s*(?P<label>.+?)\s*---\s*\n(?P<body>.*?)\n---\s*BELGE SONU:\s*(?P=label)\s*---",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parts: list[str] = []
    labels: list[str] = []
    for match in pattern.finditer(original):
        body = str(match.group("body") or "").strip()
        if not body:
            continue
        parts.append(body)
        label = " ".join(str(match.group("label") or "").split()).strip()
        if label and label not in labels:
            labels.append(label)
    return ("\n\n".join(parts).strip(), labels) if parts else ("", [])


def _document_source_payload(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None,
) -> tuple[str, str, list[str], list[str]]:
    embedded_text, labels = _embedded_attachment_payload(text)
    path, selected_paths = _resolve_document_target(text, selected_artifacts)
    if path and not embedded_text:
        return path, "", selected_paths, [Path(path).stem]
    if embedded_text:
        return "", embedded_text, [], labels
    if path:
        return path, "", selected_paths, [Path(path).stem]
    return "", "", [], labels


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
    agent_plan = build_agent_plan(steps, summary=summary)
    return {
        "summary": summary,
        "steps": steps,
        "privacyClass": privacy_class,
        "agentPlan": agent_plan,
        "stepCount": agent_plan.get("stepCount", 0),
        "agentRoles": agent_plan.get("agentRoles", []),
        "executionStrategy": agent_plan.get("executionStrategy", "single_lane"),
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
    source_path, source_text, selected_paths, _labels = _document_source_payload(text, selected_artifacts)
    if not source_path and not source_text and not any(
        token in q for token in ("dosya", "belge", "pdf", "docx", "markdown", "json", "csv", "txt")
    ):
        return None
    if not any(token in q for token in ("oku", "ozetle", "özetle", "cikar", "çıkar", "listele", "maddeler")):
        return None
    if not source_path and not source_text:
        return None
    args: dict[str, Any] = {"mode": _document_mode(text)}
    if source_path:
        args["path"] = source_path
    if source_text:
        args["text"] = source_text
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


def _document_summary_save_route(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in _DOCUMENT_SUMMARY_SAVE_TOKENS):
        return None
    if not any(token in q for token in _DOCUMENT_SAVE_TOKENS):
        return None

    source_path, source_text, selected_paths, labels = _document_source_payload(text, selected_artifacts)
    if not source_path and not source_text:
        return None

    source_label = labels[0] if labels else (Path(source_path).stem if source_path else "paylasilan-metin")
    summary_label = Path(source_label).stem.replace("_", " ").strip() or "paylaşılan metin"
    output_path = _resolve_output_path(text, ".docx", hint=f"{summary_label}-ozet")
    title = f"{summary_label} özeti"
    payload: dict[str, Any] = {
        "path": source_path,
        "text": source_text,
        "selectedPaths": selected_paths,
        "outputPath": output_path,
        "title": title,
        "overwrite": False,
    }
    skill_steps = [
        {
            "capability": "document_read",
            "description": "Kaynak içerik özetlenecek.",
            "args": {"mode": "summary"},
            "argsFromPayload": {
                "path": "path",
                "text": "text",
                "_selectedPaths": "selectedPaths",
            },
        },
        {
            "capability": "document_write",
            "description": "Özet DOCX dosyasına kaydedilecek.",
            "args": {"overwrite": False},
            "argsFromPayload": {
                "outputPath": "outputPath",
                "title": "title",
                "overwrite": "overwrite",
            },
            "argsFromPreviousResult": {"source_context": "summary"},
        },
    ]
    summary = f"{summary_label} özetlenecek ve {Path(output_path).name} olarak masaüstüne kaydedilecek."
    return RoutedTask(
        "run_skill",
        {"skillId": "document.summary_and_save", "payload": payload},
        "document_summary_save",
        intent="document_summary_save",
        confidence=0.95,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, skill_steps, "local_private"),
        steps=(
            {
                "capability": "run_skill",
                "args": {"skillId": "document.summary_and_save", "payload": payload},
                "description": summary,
            },
        ),
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


def _canvas_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("canvas", "kanvas", "tuval", "whiteboard", "layout", "board")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla", "tasarla", "design")):
        return None
    output_path = _resolve_output_path(text, ".pdf", hint=text or "elyan-canvas")
    steps = [
        {
            "capability": "canvas_write",
            "args": {"prompt": text, "outputPath": output_path, "outputFormat": "pdf", "overwrite": False},
            "description": f"{Path(output_path).name} canvas çıktısı oluşturulacak.",
        }
    ]
    return RoutedTask(
        "canvas_write",
        {"prompt": text, "outputPath": output_path, "outputFormat": "pdf", "overwrite": False},
        "canvas_write",
        intent="canvas_write",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} canvas çıktısını oluşturacağım.",
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


_RESEARCH_STRONG_TRIGGERS = {"araştır", "arastir", "araştırma", "research", "incele"}
_RESEARCH_WEAK_TRIGGERS = {"kaynak", "source", "verify"}
_RESEARCH_STOPWORDS = {
    "araştır",
    "arastir",
    "araştırma",
    "research",
    "incele",
    "kaynak",
    "source",
    "verify",
    "ver",
    "goster",
    "göster",
    "bak",
    "yap",
    "et",
    "please",
    "lutfen",
    "lütfen",
}


def _research_topic_terms(text: str) -> list[str]:
    return [
        word
        for word in _normalise(text).split()
        if word and word not in _RESEARCH_STOPWORDS
    ]


def _research_request_profile(text: str) -> tuple[str, bool]:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in (*_RESEARCH_STRONG_TRIGGERS, *_RESEARCH_WEAK_TRIGGERS)):
        return "", False
    topic = _research_topic(original)
    topic_terms = _research_topic_terms(topic)
    if not topic_terms:
        return topic, False
    if any(token in q for token in _RESEARCH_STRONG_TRIGGERS):
        return topic, True
    if any(token in q for token in ("hakkinda", "about")):
        return topic, True
    return topic, len(topic_terms) >= 2


def _email_subject(topic: str, fallback: str) -> str:
    cleaned = _strip_leading_fillers(topic) or _strip_leading_fillers(fallback)
    if cleaned:
        return f"{cleaned[:80]} hakkında notlar"
    return "Hazırlanan e-posta"


def _build_web_research_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    topic, specific = _research_request_profile(original)
    if not specific:
        return None
    q = _normalise(original)
    if _extract_email_addresses(original) and any(token in q for token in ("mail", "email", "e-posta", "gönder", "gonder", "send")):
        return None

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
    research_query, specific_research = _research_request_profile(original)
    research_query = research_query if specific_research else ""
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
    if any(token in q for token in _DOCUMENT_SUMMARY_SAVE_TOKENS) and any(token in q for token in _DOCUMENT_SAVE_TOKENS):
        path, _ = _resolve_document_target(text, selected_artifacts)
        embedded_text, _labels = _embedded_attachment_payload(text)
        if not path and not embedded_text:
            return {
                "kind": "document",
                "question": "Özetlenecek belgeyi seç veya belge içeriğini paylaş.",
            }
    if audio_requested:
        path, _ = _resolve_audio_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "audio",
                "question": "Bu ses kaydı için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    return None


# ── File system helpers ───────────────────────────────────────────────────────

_COMMON_LOCATIONS: dict[str, str] = {
    # Turkish → English path segment
    "masaustu": "Desktop",
    "masaüstü": "Desktop",
    "indirilenler": "Downloads",
    "downloads": "Downloads",
    "belgeler": "Documents",
    "documents": "Documents",
    "resimler": "Pictures",
    "pictures": "Pictures",
    "muzik": "Music",
    "müzik": "Music",
    "music": "Music",
    "videolar": "Movies",
    "filmler": "Movies",
    "movies": "Movies",
    "ev": "",
    "home": "",
}

_LOCATION_TRIGGER_PATTERNS = {
    "masaustune", "masaüstüne", "masaustunde", "masaüstünde", "masaustundeki",
    "masaüstündeki", "masaustundan", "masaüstünden", "masaustu", "masaüstü",
    "indirilenlere", "indirilenler", "indirilenlerden", "indirilenlerdeki",
    "belgelere", "belgeler", "belgelerden", "belgelerdeki",
    "desktop", "downloads", "documents",
}


def _resolve_location_path(text: str) -> str:
    """Return ~/LocationName for recognised Turkish/English location names."""
    q = _normalise(text)
    home = Path.home()
    for key, folder in _COMMON_LOCATIONS.items():
        if key in q:
            if folder:
                return str(home / folder)
            return str(home)
    return str(home / "Desktop")  # safe default when context implies a location


def _mentions_location(text: str) -> bool:
    q = _normalise(text)
    return any(tok in q for tok in _LOCATION_TRIGGER_PATTERNS)


def _extract_quoted_name(text: str) -> str:
    match = re.search(r'["\'«»„"](.+?)["\'»"]', text)
    if match:
        return match.group(1).strip()
    return ""


# Tokens that are never valid folder names on their own
_FOLDER_NAME_STOPWORDS = {
    "klasor", "klasör", "folder", "dizin", "yeni", "olustur", "oluştur",
    "yap", "masaustune", "masaüstüne", "masaustunde", "masaüstünde",
    "indirilenlere", "belgelere", "desktop", "downloads", "documents",
    "lutfen", "lütfen", "please",
}


def _extract_folder_name(text: str) -> str:
    """Extract folder name from phrases like 'X adlı klasör', 'X klasörü', 'X adında klasör'."""
    original = str(text or "").strip()
    quoted = _extract_quoted_name(original)
    if quoted:
        return quoted
    patterns = [
        r'"(.+?)"',
        r"(\w[\w\s\-\.]*?)\s+adl[ıi]\s+klasör",
        r"(\w[\w\s\-\.]*?)\s+ad[ıi]nda\s+klasör",
        r"(\w[\w\s\-\.]*?)\s+isimli\s+klasör",
        r"(?:yeni\s+)?klasör(?:ü)?\s+oluştur(?:un?)?\s+(.+)$",
        r"(?:yeni\s+)?klasör\s+yap\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, original, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip(" .,!?:;\"'")
            # Strip leading location words
            candidate = re.sub(
                r"^(?:masaüstüne|masaustune|indirilenlere|belgelere|desktop|downloads?|documents?)\s+",
                "", candidate, flags=re.IGNORECASE,
            ).strip()
            if candidate and _normalise(candidate) not in _FOLDER_NAME_STOPWORDS:
                return candidate
    return ""


def _extract_file_name(text: str) -> str:
    quoted = _extract_quoted_name(text)
    if quoted:
        return quoted
    # Look for common file patterns
    m = re.search(r"([A-Za-z0-9_\-ığüşöçİĞÜŞÖÇ]+(?:\.[a-zA-Z0-9]{1,6})+)", text)
    return m.group(1).strip() if m else ""


def _extract_rename_target(text: str) -> tuple[str, str]:
    """Returns (old_name, new_name) from rename phrases."""
    original = str(text or "").strip()
    # Normalise various quote styles to ASCII double-quote for simpler matching
    normalised_quotes = re.sub(r'[""«»„]', '"', original)
    patterns = [
        r'"(.+?)"\s+ad[ıi]n[ıi]\s+"(.+?)"\s+(?:yap|degistir|değiştir|olarak degistir)',
        r'"(.+?)"\s+(?:dosyas[ıi]n[ıi]|klasör[ü]n[ü])\s+"(.+?)"\s+(?:olarak yeniden adlandir|olarak adlandir)',
        r'"(.+?)"\s+ad[ıi]n[ıi]\s+"(.+?)"\s+(?:olarak\s+)?(?:degistir|değiştir)',
        r"(.+?)\s+ad[ıi]n[ıi]\s+(.+?)\s+(?:yap|degistir)",
    ]
    for pat in patterns:
        m = re.search(pat, normalised_quotes, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _mkdir_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    # Triggers: "klasör oluştur", "klasör yap", "yeni klasör", "dizin oluştur"
    is_mkdir = any(tok in q for tok in (
        "klasor olustur", "klasör oluştur",
        "klasor yap", "klasör yap",
        "yeni klasor", "yeni klasör",
        "dizin olustur", "dizin oluştur",
        "folder olustur", "folder oluştur",
        "create folder", "make folder", "mkdir",
        "new folder", "yeni dizin",
    ))
    if not is_mkdir:
        return None

    folder_name = _extract_folder_name(text)
    location_path = _resolve_location_path(text)

    if folder_name:
        target_path = str(Path(location_path) / folder_name)
        command = f'mkdir -p "{target_path}"'
        description = f'"{folder_name}" klasörü {Path(location_path).name} içinde oluşturulacak.'
        summary = f'{Path(location_path).name} konumunda "{folder_name}" adlı klasör oluşturacağım.'
    else:
        target_path = location_path
        command = f'mkdir -p "{target_path}/Yeni Klasör"'
        description = f"{Path(location_path).name} içinde yeni klasör oluşturulacak."
        summary = f'{Path(location_path).name} konumuna yeni bir klasör oluşturacağım.'

    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "mkdir",
        intent="file_system_mkdir",
        confidence=0.95,
        requires_confirmation=False,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _list_dir_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    triggers = (
        "klasor icerigi", "klasör içeriği",
        "dizin icerigi", "dizin içeriği",
        "dosyalari listele", "dosyaları listele",
        "dosyalari goster", "dosyaları göster",
        "icerigi goster", "içeriği göster",
        "ne var", "neler var",
        "listele", "list",
    )
    location_triggers = _LOCATION_TRIGGER_PATTERNS
    has_trigger = any(tok in q for tok in triggers)
    has_location = any(tok in q for tok in location_triggers)

    if not (has_trigger and has_location):
        # Also match "masaüstünü göster" / "indirilenler klasörü"
        if not (any(t in q for t in ("goster", "göster", "bak")) and has_location):
            return None

    location_path = _resolve_location_path(text)
    location_name = Path(location_path).name or "Ana dizin"
    command = f'ls -la "{location_path}"'
    description = f"{location_name} klasörünün içeriği listeleniyor."
    summary = f"{location_name} içindeki dosya ve klasörleri listeleceğim."
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "list_dir",
        intent="file_system_list",
        confidence=0.88,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_move_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("tasi", "taşı", "move", "transfer")):
        return None
    # Need a source and destination reference
    file_name = _extract_file_name(text)
    if not file_name and not _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES):
        return None
    dest_path = _resolve_location_path(text)
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    if src_explicit:
        src = src_explicit
    elif file_name:
        # Try to find source in common locations
        for loc in ("Desktop", "Downloads", "Documents"):
            candidate = str(Path.home() / loc / file_name)
            if Path(candidate).exists():
                src = candidate
                break
        else:
            src = str(Path.home() / "Desktop" / file_name)
    else:
        return None

    command = f'mv "{src}" "{dest_path}/"'
    description = f'"{Path(src).name}" dosyası {Path(dest_path).name} konumuna taşınacak.'
    summary = f'"{Path(src).name}" dosyasını {Path(dest_path).name} klasörüne taşıyacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_move",
        intent="file_system_move",
        confidence=0.85,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_copy_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("kopyala", "copy", "kopyasini olustur", "kopyasını oluştur", "duplicate")):
        return None
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    file_name = _extract_file_name(text)
    if not src_explicit and not file_name:
        return None
    dest_path = _resolve_location_path(text)
    src = src_explicit or str(Path.home() / "Desktop" / file_name)
    command = f'cp -r "{src}" "{dest_path}/"'
    description = f'"{Path(src).name}" dosyası {Path(dest_path).name} konumuna kopyalanacak.'
    summary = f'"{Path(src).name}" dosyasını {Path(dest_path).name} klasörüne kopyalayacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_copy",
        intent="file_system_copy",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_delete_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("sil", "delete", "remove", "kaldir", "kaldır", "cop kutusuna", "çöp kutusuna")):
        return None
    # Be conservative — require explicit file reference or quoted name
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    quoted = _extract_quoted_name(text)
    if not src_explicit and not quoted:
        return None
    src = src_explicit or str(Path.home() / "Desktop" / quoted)
    # Move to trash instead of hard delete for safety
    trash_cmd = f'osascript -e \'tell application "Finder" to delete POSIX file "{src}"\''
    description = f'"{Path(src).name}" çöp kutusuna taşınacak.'
    summary = f'"{Path(src).name}" dosyasını çöp kutusuna taşıyacağım.'
    steps = [{"capability": "shell_run", "args": {"command": trash_cmd, "use_shell": True}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": trash_cmd, "use_shell": True},
        "file_delete",
        intent="file_system_delete",
        confidence=0.9,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_rename_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("yeniden adlandir", "adini degistir", "olarak degistir", "rename", "isim degistir")):
        return None
    old_name, new_name = _extract_rename_target(text)
    if not old_name or not new_name:
        return None
    location_path = _resolve_location_path(text) if _mentions_location(text) else str(Path.home() / "Desktop")
    src = str(Path(location_path) / old_name)
    dst = str(Path(location_path) / new_name)
    command = f'mv "{src}" "{dst}"'
    description = f'"{old_name}" → "{new_name}" olarak yeniden adlandırılacak.'
    summary = f'"{old_name}" dosyasının adını "{new_name}" olarak değiştireceğim.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_rename",
        intent="file_system_rename",
        confidence=0.88,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _create_file_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("dosya olustur", "dosyasi olustur", "yeni dosya", "create file", "txt olustur", "new file")):
        return None
    file_name = _extract_file_name(text) or _extract_folder_name(text) or "yeni-dosya.txt"
    if not Path(file_name).suffix:
        file_name += ".txt"
    location_path = _resolve_location_path(text)
    target_path = str(Path(location_path) / file_name)
    command = f'touch "{target_path}"'
    description = f'"{file_name}" dosyası {Path(location_path).name} konumunda oluşturulacak.'
    summary = f'{Path(location_path).name} konumunda "{file_name}" adlı yeni dosya oluşturacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "create_file",
        intent="file_system_create",
        confidence=0.9,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _desktop_document_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    """Resolve 'masaüstündeki [dosya]' patterns for document operations."""
    if not _mentions_location(text):
        return None
    q = _normalise(text)
    if not any(tok in q for tok in ("ozetle", "özetle", "oku", "cikar", "çıkar", "analiz", "incele", "summary", "summarize")):
        return None
    # Try to extract file name from text
    file_name = _extract_file_name(text)
    if not file_name:
        return None
    location_path = _resolve_location_path(text)
    candidate = str(Path(location_path) / file_name)
    src = candidate
    suffix = Path(src).suffix.lower() if file_name else ""
    if suffix in _DATA_SUFFIXES:
        return RoutedTask(
            "data_analyze",
            {"path": src, "mode": _data_mode(text)},
            "desktop_data_analyze",
            intent="data_analyze",
            confidence=0.82,
            privacy_class="local_private",
        )
    # Default: document read/summarize
    return RoutedTask(
        "document_read",
        {"path": src, "mode": _document_mode(text)},
        "desktop_document_read",
        intent="document_read",
        confidence=0.80,
        privacy_class="local_private",
    )


# ── route_text_to_tool ────────────────────────────────────────────────────────

def route_text_to_tool(
    text: str,
    *,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> RoutedTask | None:
    original = str(text or "").strip()
    if not original:
        return None
    q = _normalise(original)

    # ── File system operations (highest priority — very specific intents) ──────
    mkdir = _mkdir_route(original)
    if mkdir is not None:
        return mkdir

    file_rename = _file_rename_route(original)
    if file_rename is not None:
        return file_rename

    file_delete = _file_delete_route(original)
    if file_delete is not None:
        return file_delete

    file_move = _file_move_route(original)
    if file_move is not None:
        return file_move

    file_copy = _file_copy_route(original)
    if file_copy is not None:
        return file_copy

    list_dir = _list_dir_route(original)
    if list_dir is not None:
        return list_dir

    create_file = _create_file_route(original)
    if create_file is not None:
        return create_file

    # Desktop-located document operations ("masaüstündeki belgeyi özetle")
    desktop_doc = _desktop_document_route(original, selected_artifacts)
    if desktop_doc is not None:
        return desktop_doc

    # ── Scheduled / calendar ──────────────────────────────────────────────────
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

    document_summary_save = _document_summary_save_route(original, selected_artifacts)
    if document_summary_save is not None:
        return document_summary_save

    canvas_write = _canvas_write_route(original)
    if canvas_write is not None:
        return canvas_write

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
            "ss al",
            "screenshot al",
            "ekran goruntusu al",
            "ekran görüntüsü al",
            "ekran resmini al",
            "ekranin resmini al",
            "ekranın resmini al",
            "ekrani cek",
            "ekranı çek",
            "ekran fotosu al",
            "ekran fotografi al",
            "ekran fotoğrafı al",
            "ekranda ne var",
            "ekrani analiz",
            "ekran analizi",
            "bu hatayi oku",
            "buradaki hatayi oku",
            "buradaki hatayi incele",
            "pencereyi analiz",
            "aktif pencereyi analiz",
            "aktif pencereye bak",
            "bu pencereyi oku",
            "burada ne var",
            "ne goruyorsun",
            "ekrana bak",
            "masaustunde ne var",
            "masaustune bak",
            "masaustunu analiz",
            "masaustunu goster",
            "bilgisayarda ne var",
            "bilgisayarda ne acik",
            "bilgisayara bak",
            "ne acik",
            "what is on",
            "whats on",
            "what's on",
            "desktop",
            "screen",
        )
    ):
        screenshot_terms = {
            "ss al",
            "screenshot al",
            "ekran goruntusu al",
            "ekran görüntüsü al",
            "ekran resmini al",
            "ekranin resmini al",
            "ekranın resmini al",
            "ekrani cek",
            "ekranı çek",
            "ekran fotosu al",
            "ekran fotografi al",
            "ekran fotoğrafı al",
        }
        if any(token in q for token in screenshot_terms):
            return RoutedTask(
                "desktop_operator.observe_screen",
                {"query": original, "target": "active_window", "preserveScreenshot": True},
                "screen_screenshot",
                intent="screen_screenshot",
                confidence=0.97,
                privacy_class="local_private",
            )
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
            r"youtube(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?\s+(.+?)\s+(?:ac|aç|cal|çal|oynat|ara)$",
            r"(.+?)\s+youtube(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?\s+(?:ac|aç|cal|çal|oynat)$",
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
            r"(?:google(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?|web(?:['’]?(?:de|den)|\s+(?:de|den))?|internette)\s+(.+?)\s+(?:ara|search)$",
            r"(.+?)\s+(?:google(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?|web(?:['’]?(?:de|den)|\s+(?:de|den))?|internette)\s+(?:ara|search)$",
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

    if any(token in q for token in ("onu kapat", "bunu kapat", "aktif pencereyi kapat", "bu pencereyi kapat")):
        return RoutedTask("close_app", {"app_name": ""}, "close_active_app", intent="close_app", confidence=0.93, privacy_class="local_private")

    focus_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:one getir|öne getir|one al|öne al|odakla|focus|bring to front)$",
            r"(?:one getir|öne getir|one al|öne al|odakla|focus|bring to front)\s+(.+)$",
        ],
        original,
    )
    if focus_target:
        focus_target = _clean_app_name(focus_target)
        if not _is_generic_window_reference(focus_target):
            return RoutedTask("open_app", {"app_name": focus_target}, "focus_app", intent="focus_app", confidence=0.92, privacy_class="local_private")

    restart_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:yeniden ac|yeniden aç|restart|relaunch)$",
            r"(?:yeniden ac|yeniden aç|restart|relaunch)\s+(.+)$",
        ],
        original,
    )
    if restart_target:
        restart_target = _clean_app_name(restart_target)
        if restart_target and not _is_generic_window_reference(restart_target):
            steps = [
                {"capability": "close_app", "args": {"app_name": restart_target}, "description": f"{restart_target} kapatılacak."},
                {"capability": "open_app", "args": {"app_name": restart_target}, "description": f"{restart_target} yeniden açılacak."},
            ]
            summary = f"{restart_target} kapatılıp yeniden açılacak."
            return RoutedTask(
                "close_app",
                {"app_name": restart_target},
                "restart_app",
                intent="restart_app",
                confidence=0.9,
                requires_confirmation=True,
                is_multi_step=True,
                privacy_class="local_private",
                plan_preview=_build_plan_summary(summary, steps, "local_private"),
                steps=tuple(steps),
            )

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
            r"(?:terminalde|terminal[a-z]*|komut satiri[a-z]*|shell[a-z]*)\s+(.+?)\s+(?:calistir|çalıştır|run|execute|exec)$",
            r"(?:terminalde|terminal[a-z]*|komut satiri[a-z]*|shell[a-z]*)\s+(.+)$",
            r"(?:calistir|çalıştır|run|execute)\s+([\w\-\.]+(?:\s+.+)?)$",
            r"^((?:ls|dir|pwd|echo|cat|grep|find|ps|top|df|du|ping|curl|wget|git|npm|pip|python|python3|node|brew|apt|yum|dnf|pacman|choco|winget)\s*.+)$",
        ],
        original,
    )
    if command:
        # Strip leading quotes if LLM wrapped the command
        command = command.strip("'\"").strip()
        use_shell = any(op in command for op in ("&&", "||", "|", ";", ">", "<", "$(", "`"))
        summary = f"`{command}` komutu çalıştırılacak."
        steps = [
            {
                "capability": "shell_run",
                "args": {"command": command, "use_shell": use_shell},
                "description": summary,
            }
        ]
        return RoutedTask(
            "shell_run",
            {"command": command, "use_shell": use_shell},
            "shell_command",
            intent="shell_command",
            confidence=0.97,
            requires_confirmation=True,
            privacy_class="local_private",
            plan_preview=_build_plan_summary(summary, steps, "local_private"),
            steps=tuple(steps),
        )

    return None
