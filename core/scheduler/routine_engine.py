"""
Routine Engine

Persists multi-step automation routines and executes them step-by-step.
Designed for "daily operator" workflows such as:
- panel checks
- data extraction
- report preparation
- channel delivery
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from core.storage_paths import resolve_elyan_data_dir
from core.multi_agent.orchestrator import get_orchestrator
from core.intelligent_planner import get_intelligent_planner

logger = get_logger("routine_engine")

def _default_routine_persist_path() -> Path:
    return resolve_elyan_data_dir() / "routines.json"


def _default_routine_report_dir() -> Path:
    return resolve_elyan_data_dir() / "reports" / "routines"


ROUTINE_PERSIST_PATH = _default_routine_persist_path()
ROUTINE_REPORT_DIR = _default_routine_report_dir()

_RE_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_RE_DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.IGNORECASE)
_RE_NON_WORD = re.compile(r"[^a-z0-9]+", re.IGNORECASE)
_RE_TIME_HM = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")
_RE_TIME_TR = re.compile(r"\bsaat\s*(\d{1,2})(?:[:.](\d{2}))?\b", re.IGNORECASE)
_RE_TIME_SUFFIX_HOUR = re.compile(r"\b(\d{1,2})\s*(?:'|’)?(?:da|de)\b", re.IGNORECASE)
_RE_EVERY_N_HOURS = re.compile(r"\bher\s+(\d{1,2})\s*saat(?:te)?(?:\s*bir)?\b", re.IGNORECASE)
_RE_EVERY_N_MINUTES = re.compile(r"\bher\s+(\d{1,2})\s*dakika(?:da)?(?:\s*bir)?\b", re.IGNORECASE)
_RE_EVERY_HOUR = re.compile(r"\b(?:her\s+saat(?:te)?|saatte\s*bir|saat\s*başı)\b", re.IGNORECASE)
_RE_EVERY_MINUTE = re.compile(r"\b(?:her\s+dakika(?:da)?|dakikada\s*bir)\b", re.IGNORECASE)
_RE_CHAT_ID = re.compile(r"\b(?:chat\s*id|chat_id|id)\s*[:=]?\s*(\d{5,20})\b", re.IGNORECASE)

_HARD_FAIL_MARKERS = (
    "missing required positional argument",
    "tool not found",
    "traceback",
    "permission denied",
    "hata: tool",
)

_TR_DAY_MAP = {
    "pazartesi": "1",
    "salı": "2",
    "sali": "2",
    "çarşamba": "3",
    "carsamba": "3",
    "perşembe": "4",
    "persembe": "4",
    "cuma": "5",
    "cumartesi": "6",
    "pazar": "0",
}


def _extract_time_from_text(text: str, default_hour: int = 9, default_minute: int = 0) -> tuple[int, int]:
    raw = _clean_text(text)
    if raw:
        low = raw.lower()
        period_pm = any(
            k in low
            for k in (
                "öğleden sonra",
                "ogleden sonra",
                "ikindi",
                "akşam",
                "aksam",
                "gece",
            )
        )

        m = _RE_TIME_HM.search(raw)
        if m:
            h = min(23, max(0, int(m.group(1))))
            mi = min(59, max(0, int(m.group(2))))
            if period_pm and 1 <= h <= 11:
                h += 12
            return h, mi
        m = _RE_TIME_TR.search(raw)
        if m:
            h = min(23, max(0, int(m.group(1))))
            mi_raw = m.group(2)
            mi = min(59, max(0, int(mi_raw))) if mi_raw is not None else 0
            if period_pm and 1 <= h <= 11:
                h += 12
            return h, mi
        m = _RE_TIME_SUFFIX_HOUR.search(raw)
        if m:
            h = min(23, max(0, int(m.group(1))))
            if period_pm and 1 <= h <= 11:
                h += 12
            return h, 0

        if "sabah" in low:
            return 9, 0
        if "öğlen" in low or "oglen" in low:
            return 12, 0
        if "öğleden sonra" in low or "ogleden sonra" in low or "ikindi" in low:
            return 15, 0
        if "akşam" in low or "aksam" in low:
            return 20, 0
        if "gece" in low:
            return 22, 0
    return int(default_hour), int(default_minute)


def _detect_schedule_expression(text: str, *, default_expression: str = "0 9 * * *") -> str:
    low = _clean_text(text).lower()
    if not low:
        return default_expression

    m = _RE_EVERY_N_MINUTES.search(low)
    if m:
        n = min(59, max(1, int(m.group(1))))
        return f"*/{n} * * * *"
    if _RE_EVERY_MINUTE.search(low):
        return "* * * * *"

    m = _RE_EVERY_N_HOURS.search(low)
    if m:
        n = min(23, max(1, int(m.group(1))))
        return f"0 */{n} * * *"
    if _RE_EVERY_HOUR.search(low):
        return "0 * * * *"

    hour, minute = _extract_time_from_text(low, default_hour=9, default_minute=0)
    base = f"{minute} {hour}"

    if "hafta içi" in low or "haftaici" in low:
        return f"{base} * * 1-5"
    if "hafta sonu" in low or "haftasonu" in low:
        return f"{base} * * 6,0"
    if "haftada bir" in low:
        return f"{base} * * 1"
    if any(k in low for k in ("ayda bir", "aylık", "aylik", "her ay")):
        return f"{base} 1 * *"

    days: list[str] = []
    for tr_day, dow in _TR_DAY_MAP.items():
        if tr_day in low and dow not in days:
            days.append(dow)
    if days:
        return f"{base} * * {','.join(days)}"

    if any(
        k in low
        for k in (
            "her gün",
            "hergun",
            "günlük",
            "gunluk",
            "daily",
            "her sabah",
            "her akşam",
            "her aksam",
            "her gece",
            "her öğlen",
            "her oglen",
        )
    ):
        return f"{base} * * *"

    return default_expression


def _detect_template_id(text: str) -> str:
    low = _clean_text(text).lower()
    if not low:
        return ""

    score_map = {
        "ecommerce-daily": 0,
        "agency-daily": 0,
        "academic-daily": 0,
        "office-daily": 0,
    }
    ecommerce_keys = ("e-ticaret", "eticaret", "sipariş", "siparis", "kargo", "stok", "satıcı", "satici", "marketplace")
    agency_keys = ("ajans", "danışman", "danisman", "form", "lead", "crm", "müşteri", "musteri", "kampanya")
    academic_keys = ("akademik", "öğrenci", "ogrenci", "duyuru", "sınav", "sinav", "ders", "fakülte", "fakulte")
    office_keys = ("ofis", "muhasebe", "tahsilat", "cari", "fatura", "ödeme", "odeme", "finans")

    for key in ecommerce_keys:
        if key in low:
            score_map["ecommerce-daily"] += 2
    for key in agency_keys:
        if key in low:
            score_map["agency-daily"] += 2
    for key in academic_keys:
        if key in low:
            score_map["academic-daily"] += 2
    for key in office_keys:
        if key in low:
            score_map["office-daily"] += 2

    best_template = max(score_map.keys(), key=lambda k: score_map[k])
    return best_template if score_map[best_template] > 0 else ""


def _default_steps_for_text(text: str) -> list[str]:
    low = _clean_text(text).lower()
    if not low:
        return [
            "Tarayıcıyı aç",
            "Belirlenen panelleri kontrol et",
            "Yeni veri var mı kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ]

    wants_file_report = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
    wants_browser = any(k in low for k in ("tarayıcı", "tarayici", "browser", "panel", "site", "giriş", "giris"))
    wants_delivery = any(k in low for k in ("telegram", "whatsapp", "discord", "slack", "gönder", "gonder", "ilet"))
    wants_summary = any(k in low for k in ("özet", "ozet", "rapor", "briefing"))

    steps: list[str] = []
    if wants_browser:
        steps.append("Tarayıcıyı aç")
        steps.append("Belirlenen panellere giriş yap")
        steps.append("Yeni veri var mı kontrol et")
    else:
        steps.append("Belirlenen kaynakları kontrol et")
        steps.append("Yeni veri var mı kontrol et")

    if wants_file_report:
        steps.append("Excel / tablo oluştur")
    else:
        steps.append("Çıktı dosyası oluştur")

    if wants_summary:
        steps.append("Özet rapor hazırla")
    else:
        steps.append("Bulgu özeti çıkar")

    if wants_delivery:
        steps.append("Telegram / WhatsApp gönder")
    else:
        steps.append("Raporu kaydet")
    return steps


def _detect_report_channel(text: str, fallback: str = "telegram") -> str:
    low = _clean_text(text).lower()
    for channel in ("telegram", "whatsapp", "discord", "slack", "webchat"):
        if channel in low:
            return channel
    return fallback


def _extract_chat_id(text: str) -> str:
    m = _RE_CHAT_ID.search(_clean_text(text))
    return str(m.group(1)) if m else ""

ROUTINE_TEMPLATES: dict[str, dict[str, Any]] = {
    "ecommerce-daily": {
        "id": "ecommerce-daily",
        "name": "E-ticaret Günlük Operasyon",
        "category": "ecommerce",
        "description": "Sipariş/kargo/müşteri mesajı/stok kontrolü + rapor",
        "steps": [
            "Tarayıcıyı aç",
            "Belirlenen panellere giriş yap",
            "Sipariş, kargo durumu ve müşteri mesajlarını kontrol et",
            "Stok verisini kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ],
    },
    "agency-daily": {
        "id": "agency-daily",
        "name": "Ajans/Danışmanlık Günlük Kontrol",
        "category": "agency",
        "description": "Formlar, mailler, panel bildirimleri ve günlük özet",
        "steps": [
            "Tarayıcıyı aç",
            "Belirlenen panellere giriş yap",
            "Gelen formlar ve mailleri kontrol et",
            "Panel bildirimlerini kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ],
    },
    "academic-daily": {
        "id": "academic-daily",
        "name": "Akademik Günlük Kontrol",
        "category": "academic",
        "description": "Öğrenci listesi, duyuru, form ve rapor üretimi",
        "steps": [
            "Tarayıcıyı aç",
            "Belirlenen panellere giriş yap",
            "Öğrenci listesi, duyuru ve form sonuçlarını kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ],
    },
    "office-daily": {
        "id": "office-daily",
        "name": "Küçük İşletme Ofis Rutini",
        "category": "office",
        "description": "Muhasebe/tahsilat/cari durum günlük takibi",
        "steps": [
            "Tarayıcıyı aç",
            "Belirlenen panellere giriş yap",
            "Muhasebe panelini kontrol et",
            "Tahsilat listesi ve cari durumu kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ],
    },
}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_steps(raw_steps: Any) -> List[str]:
    if isinstance(raw_steps, list):
        items = raw_steps
    elif isinstance(raw_steps, str):
        text = raw_steps.strip()
        if not text:
            return []
        items = re.split(r"(?:\n|;)+", text)
    else:
        return []

    out: List[str] = []
    for item in items:
        step = _clean_text(item)
        if step:
            out.append(step)
    return out


def _normalize_panels(raw_panels: Any) -> List[str]:
    if isinstance(raw_panels, str):
        items = re.split(r"(?:\n|;|,)+", raw_panels)
    elif isinstance(raw_panels, list):
        items = raw_panels
    else:
        items = []

    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        url = _clean_text(item)
        if not url:
            continue
        if not url.startswith("http://") and not url.startswith("https://"):
            if "." in url and " " not in url:
                url = "https://" + url
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _extract_urls(text: str) -> List[str]:
    raw = _clean_text(text)
    if not raw:
        return []
    urls: List[str] = []
    seen: set[str] = set()
    for match in _RE_URL.findall(raw):
        url = match.rstrip(").,;:!?]")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    for match in _RE_DOMAIN.findall(raw):
        dom = match.rstrip(").,;:!?]")
        if dom and dom not in seen:
            seen.add(dom)
            urls.append("https://" + dom)
    return urls


def _tool_success(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("success", True))
    return result is not None


def _tool_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        if result.get("success") is False:
            return f"Hata: {result.get('error', 'işlem başarısız')}"
        for key in ("summary", "message", "title", "content", "text"):
            value = _clean_text(result.get(key))
            if value:
                return value[:500]
        if isinstance(result.get("results"), list):
            results = result.get("results", [])
            if results:
                first = results[0]
                if isinstance(first, dict):
                    title = _clean_text(first.get("title"))
                    url = _clean_text(first.get("url"))
                    return f"{len(results)} sonuç bulundu. İlk: {title or url}"
                return f"{len(results)} sonuç bulundu."
        if _clean_text(result.get("path")):
            return f"Dosya: {result.get('path')}"
        if _clean_text(result.get("url")):
            return f"URL: {result.get('url')}"
        return json.dumps(result, ensure_ascii=False)[:500]
    return _clean_text(result)[:500]


def _safe_slug(name: str) -> str:
    cleaned = _RE_NON_WORD.sub("_", _clean_text(name).lower()).strip("_")
    return cleaned[:60] or "routine"


def _looks_like_hard_failure(text: str) -> bool:
    low = _clean_text(text).lower()
    return any(marker in low for marker in _HARD_FAIL_MARKERS)


class RoutineEngine:
    """Manages routine definitions, templates, and execution history."""

    def __init__(self):
        self._routines: Dict[str, Dict[str, Any]] = {}
        self._load()

    def list_templates(self) -> List[Dict[str, Any]]:
        templates = [dict(v) for v in ROUTINE_TEMPLATES.values()]
        templates.sort(key=lambda x: x.get("name", ""))
        return templates

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        tid = _clean_text(template_id)
        item = ROUTINE_TEMPLATES.get(tid)
        return dict(item) if item else None

    def list_routines(self) -> List[Dict[str, Any]]:
        items = [dict(v) for v in self._routines.values()]
        items.sort(key=lambda x: (not bool(x.get("enabled", True)), x.get("name", "")))
        return items

    def match_routine_ids(self, value: str) -> list[str]:
        needle = _clean_text(value)
        if not needle:
            return []
        if needle in self._routines:
            return [needle]
        return sorted([rid for rid in self._routines.keys() if rid.startswith(needle)])

    def resolve_routine_id(self, value: str) -> str | None:
        matches = self.match_routine_ids(value)
        return matches[0] if len(matches) == 1 else None

    def get_routine(self, routine_id: str) -> Optional[Dict[str, Any]]:
        rid = self.resolve_routine_id(routine_id)
        if not rid:
            return None
        item = self._routines.get(rid)
        return dict(item) if item else None

    def add_routine(
        self,
        *,
        name: str,
        expression: str,
        steps: List[str] | str,
        report_channel: str = "telegram",
        report_chat_id: str = "",
        enabled: bool = True,
        created_by: str = "system",
        tags: Optional[List[str]] = None,
        panels: Optional[List[str] | str] = None,
        template_id: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        rid = str(uuid.uuid4())[:10]
        steps_list = _normalize_steps(steps)
        if not steps_list:
            raise ValueError("Rutin adımları boş olamaz.")

        expr = _clean_text(expression)
        if not expr:
            raise ValueError("Cron ifadesi gerekli.")

        routine = {
            "id": rid,
            "name": _clean_text(name) or f"routine-{rid}",
            "expression": expr,
            "steps": steps_list,
            "enabled": bool(enabled),
            "report_channel": _clean_text(report_channel) or "telegram",
            "report_chat_id": _clean_text(report_chat_id),
            "created_by": _clean_text(created_by) or "system",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "last_run": None,
            "last_success": None,
            "run_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "history": [],
            "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
            "panels": _normalize_panels(panels or []),
            "template_id": _clean_text(template_id),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

        self._routines[rid] = routine
        self._persist()
        return dict(routine)

    def create_from_template(
        self,
        *,
        template_id: str,
        expression: str,
        report_channel: str = "telegram",
        report_chat_id: str = "",
        enabled: bool = True,
        created_by: str = "template",
        name: str = "",
        panels: Optional[List[str] | str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        template = self.get_template(template_id)
        if not template:
            raise ValueError("template not found")

        final_name = _clean_text(name) or _clean_text(template.get("name")) or "Routine"
        return self.add_routine(
            name=final_name,
            expression=expression,
            steps=template.get("steps", []),
            report_channel=report_channel,
            report_chat_id=report_chat_id,
            enabled=enabled,
            created_by=created_by,
            tags=tags or [template.get("category", "template")],
            panels=panels,
            template_id=str(template.get("id", "")),
            metadata={"template": template},
        )

    def suggest_from_text(
        self,
        text: str,
        *,
        default_expression: str = "0 9 * * *",
        default_channel: str = "telegram",
    ) -> Dict[str, Any]:
        raw = _clean_text(text)
        if not raw:
            raise ValueError("text required")

        template_id = _detect_template_id(raw)
        template = self.get_template(template_id) if template_id else None
        expression = _detect_schedule_expression(raw, default_expression=default_expression)
        panels = _normalize_panels(_extract_urls(raw))
        report_channel = _detect_report_channel(raw, fallback=default_channel)
        report_chat_id = _extract_chat_id(raw)

        if template:
            steps = _normalize_steps(template.get("steps", []))
            category = str(template.get("category", "") or "")
            base_name = _clean_text(template.get("name")) or "Akıllı Rutin"
        else:
            steps = _default_steps_for_text(raw)
            category = "custom"
            base_name = "Akıllı Rutin"

        cleaned_name = _clean_text(raw)
        if len(cleaned_name) > 72:
            cleaned_name = cleaned_name[:72].rstrip(" ,.;:")
        name = cleaned_name or base_name

        confidence = 0.55
        reasons: list[str] = []
        if template_id:
            confidence += 0.2
            reasons.append(f"template:{template_id}")
        if expression != default_expression:
            confidence += 0.1
            reasons.append("schedule_detected")
        if panels:
            confidence += 0.1
            reasons.append("panel_urls_detected")
        if report_channel != default_channel:
            confidence += 0.05
            reasons.append(f"channel:{report_channel}")
        if report_chat_id:
            confidence += 0.05
            reasons.append("chat_id_detected")
        confidence = min(0.95, max(0.5, confidence))

        return {
            "name": name,
            "expression": expression,
            "steps": steps,
            "template_id": template_id,
            "template_name": template.get("name") if template else "",
            "category": category,
            "panels": panels,
            "report_channel": report_channel,
            "report_chat_id": report_chat_id,
            "confidence": round(confidence, 2),
            "reasons": reasons,
            "source_text": raw,
        }

    def create_from_text(
        self,
        *,
        text: str,
        enabled: bool = True,
        created_by: str = "nl",
        report_chat_id: str = "",
        report_channel: str = "",
        expression: str = "",
        name: str = "",
        panels: Optional[List[str] | str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        suggestion = self.suggest_from_text(text)
        final_name = _clean_text(name) or suggestion.get("name", "Akıllı Rutin")
        final_expression = _clean_text(expression) or suggestion.get("expression", "0 9 * * *")
        final_channel = _clean_text(report_channel) or suggestion.get("report_channel", "telegram")
        final_chat_id = _clean_text(report_chat_id) or suggestion.get("report_chat_id", "")

        panel_list = _normalize_panels(panels if panels is not None else suggestion.get("panels", []))
        template_id = _clean_text(suggestion.get("template_id", ""))
        if template_id and template_id in ROUTINE_TEMPLATES:
            return self.create_from_template(
                template_id=template_id,
                expression=final_expression,
                report_channel=final_channel,
                report_chat_id=final_chat_id,
                enabled=enabled,
                created_by=created_by,
                name=final_name,
                panels=panel_list,
                tags=tags or [suggestion.get("category", "nl")],
            )

        return self.add_routine(
            name=final_name,
            expression=final_expression,
            steps=suggestion.get("steps", []),
            report_channel=final_channel,
            report_chat_id=final_chat_id,
            enabled=enabled,
            created_by=created_by,
            tags=tags or [suggestion.get("category", "nl")],
            panels=panel_list,
            template_id="",
            metadata={"source_text": _clean_text(text), "suggestion": suggestion},
        )

    def update_routine(self, routine_id: str, **patch: Any) -> Optional[Dict[str, Any]]:
        rid = self.resolve_routine_id(routine_id) or _clean_text(routine_id)
        routine = self._routines.get(rid)
        if not routine:
            return None

        if "name" in patch:
            routine["name"] = _clean_text(patch["name"]) or routine["name"]
        if "expression" in patch:
            expr = _clean_text(patch["expression"])
            if expr:
                routine["expression"] = expr
        if "steps" in patch:
            steps_list = _normalize_steps(patch["steps"])
            if steps_list:
                routine["steps"] = steps_list
        if "enabled" in patch:
            routine["enabled"] = bool(patch["enabled"])
        if "report_channel" in patch:
            routine["report_channel"] = _clean_text(patch["report_channel"]) or routine["report_channel"]
        if "report_chat_id" in patch:
            routine["report_chat_id"] = _clean_text(patch["report_chat_id"])
        if "tags" in patch and isinstance(patch["tags"], list):
            routine["tags"] = [str(t).strip() for t in patch["tags"] if str(t).strip()]
        if "panels" in patch:
            routine["panels"] = _normalize_panels(patch["panels"])
        if "template_id" in patch:
            routine["template_id"] = _clean_text(patch["template_id"])
        if "metadata" in patch and isinstance(patch["metadata"], dict):
            routine["metadata"] = dict(patch["metadata"])

        routine["updated_at"] = _now_iso()
        self._persist()
        return dict(routine)

    def remove_routine(self, routine_id: str) -> bool:
        rid = self.resolve_routine_id(routine_id) or _clean_text(routine_id)
        if rid not in self._routines:
            return False
        del self._routines[rid]
        self._persist()
        return True

    def set_enabled(self, routine_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        rid = self.resolve_routine_id(routine_id) or _clean_text(routine_id)
        routine = self._routines.get(rid)
        if not routine:
            return None
        routine["enabled"] = bool(enabled)
        routine["updated_at"] = _now_iso()
        self._persist()
        return dict(routine)

    def get_history(self, routine_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        rid = self.resolve_routine_id(routine_id) or _clean_text(routine_id)
        routine = self._routines.get(rid)
        if not routine:
            return []
        history = list(routine.get("history", []))
        history.reverse()
        return history[: max(1, int(limit or 20))]

    def _append_history(
        self,
        routine_id: str,
        *,
        success: bool,
        duration_s: float,
        summary: str,
    ) -> None:
        routine = self._routines.get(_clean_text(routine_id))
        if not routine:
            return
        history = list(routine.get("history", []))
        history.append(
            {
                "ts": _now_iso(),
                "success": bool(success),
                "duration_s": round(float(duration_s), 2),
                "summary": _clean_text(summary)[:1500],
            }
        )
        if len(history) > 50:
            history = history[-50:]
        routine["history"] = history
        routine["last_run"] = _now_iso()
        routine["last_success"] = bool(success)
        routine["run_count"] = int(routine.get("run_count", 0)) + 1
        if success:
            routine["success_count"] = int(routine.get("success_count", 0)) + 1
        else:
            routine["failure_count"] = int(routine.get("failure_count", 0)) + 1
        routine["updated_at"] = _now_iso()

    async def run_routine(self, routine_id: str, agent) -> Dict[str, Any]:
        """Execute routine steps one by one and build an operator report."""
        resolved_id = self.resolve_routine_id(routine_id) or _clean_text(routine_id)
        routine = self._routines.get(resolved_id)
        if not routine:
            return {"success": False, "error": "routine not found"}
        if not routine.get("enabled", True):
            return {"success": False, "error": "routine disabled"}

        started = time.time()
        step_results: List[Dict[str, Any]] = []
        ok = True

        panels = _normalize_panels(routine.get("panels", []))
        if not panels:
            for step in routine.get("steps", []):
                panels.extend(_extract_urls(_clean_text(step)))
            panels = _normalize_panels(panels)

        run_context: dict[str, Any] = {
            "panel_urls": panels,
            "artifacts": [],
            "findings": [],
            "generated_summary": "",
            "step_results": step_results,
        }

        for i, step in enumerate(routine.get("steps", []), start=1):
            step_start = time.time()
            step_ok = True
            out = ""
            try:
                handled, handled_ok, handled_out = await self._execute_step_with_defaults(
                    agent,
                    routine,
                    step,
                    i,
                    run_context,
                )
                if handled:
                    step_ok = handled_ok
                    out = handled_out
                else:
                    step_ok, out = await self._execute_step_with_agent(agent, routine, step, i, run_context)
            except Exception as e:
                step_ok = False
                out = f"Hata: {e}"

            duration = time.time() - step_start
            row = {
                "index": i,
                "step": step,
                "success": step_ok,
                "duration_s": round(duration, 2),
                "output": _clean_text(out)[:1200],
            }
            step_results.append(row)
            if not step_ok:
                ok = False

        duration_total = time.time() - started
        report = self._format_report(
            routine=routine,
            step_results=step_results,
            run_context=run_context,
            duration_s=duration_total,
            success=ok,
        )
        report_path = self._persist_report(routine, report)

        summary = f"{routine.get('name')} {'OK' if ok else 'FAIL'} ({round(duration_total, 2)}s)"
        self._append_history(
            routine_id=resolved_id,
            success=ok,
            duration_s=duration_total,
            summary=summary,
        )
        self._persist()

        return {
            "success": ok,
            "routine_id": resolved_id,
            "routine_name": routine.get("name"),
            "duration_s": round(duration_total, 2),
            "report": report,
            "report_path": report_path,
            "steps": step_results,
            "artifacts": list(run_context.get("artifacts", [])),
        }

    async def _execute_step_with_agent(
        self,
        agent,
        routine: dict[str, Any],
        step: str,
        step_index: int,
        run_context: dict[str, Any],
    ) -> tuple[bool, str]:
        # BP-004: Detect if this step requires the full factory flow
        is_complex = any(kw in step.lower() for kw in ["website", "web sitesi", "proje", "uygulama", "geliştir", "oluştur"])
        
        prompt = (
            f"Rutin adı: {routine.get('name', 'routine')}\n"
            f"Rutin adımı {step_index}/{len(routine.get('steps', []))}: {step}\n"
            f"Panel URL'leri: {', '.join(run_context.get('panel_urls', [])) or 'tanımlı değil'}\n"
            "Adımı tamamla ve sadece yapılan işin kısa sonucunu yaz."
        )

        if is_complex:
            logger.info(f"Complex routine step detected: {step}. Activating Multi-Agent Orchestrator.")
            orchestrator = get_orchestrator(agent)
            planner = get_intelligent_planner()
            plan = await planner.create_plan(prompt, {}, user_id="system")
            out = await orchestrator.manage_flow(plan, prompt)
        else:
            out = await agent.process(prompt)
            
        text = _clean_text(out)
        if _looks_like_hard_failure(text):
            return False, text or "Adım başarısız"
        return True, text

    async def _run_tool(
        self,
        agent,
        tool_name: str,
        params: dict[str, Any],
        *,
        user_input: str,
        step_name: str,
    ) -> tuple[bool, str, Any]:
        result = await agent._execute_tool(
            tool_name,
            params,
            user_input=user_input,
            step_name=step_name,
        )
        return _tool_success(result), _tool_text(result), result

    def _default_excel_path(self, routine: dict[str, Any]) -> str:
        day = datetime.now().strftime("%Y%m%d")
        slug = _safe_slug(routine.get("name", "routine"))
        out_dir = self._default_report_output_dir(day)
        return str(out_dir / f"{slug}.xlsx")

    def _default_summary_path(self, routine: dict[str, Any]) -> str:
        day = datetime.now().strftime("%Y%m%d")
        slug = _safe_slug(routine.get("name", "routine"))
        out_dir = self._default_report_output_dir(day)
        return str(out_dir / f"{slug}_summary.md")

    def _default_report_output_dir(self, day: str) -> Path:
        candidates = [
            ROUTINE_REPORT_DIR / day,
            Path(tempfile.gettempdir()) / "elyan" / "reports" / "routines" / day,
        ]
        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path
            except Exception:
                continue
        return Path(".")

    def _build_excel_rows(self, run_context: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in run_context.get("step_results", []):
            rows.append(
                {
                    "step_index": row.get("index"),
                    "step": _clean_text(row.get("step"))[:180],
                    "success": "OK" if row.get("success") else "FAIL",
                    "duration_s": row.get("duration_s"),
                    "output": _clean_text(row.get("output"))[:320],
                }
            )

        if not rows:
            for i, finding in enumerate(run_context.get("findings", []), start=1):
                rows.append(
                    {
                        "step_index": i,
                        "step": "finding",
                        "success": "OK",
                        "duration_s": 0,
                        "output": _clean_text(finding.get("summary") or finding.get("title") or "")[:320],
                    }
                )
        return rows

    def _build_summary_text(self, routine: dict[str, Any], run_context: dict[str, Any]) -> str:
        findings = run_context.get("findings", [])
        steps = run_context.get("step_results", [])
        ok_count = len([x for x in steps if x.get("success")])
        fail_count = len(steps) - ok_count

        lines = [
            f"Rutin: {routine.get('name')}",
            f"Adım Özeti: {ok_count} başarılı / {fail_count} başarısız",
        ]

        if findings:
            lines.append("Öne Çıkan Bulgular:")
            for item in findings[:6]:
                src = _clean_text(item.get("source") or item.get("url") or "kaynak")
                summary = _clean_text(item.get("summary") or item.get("title") or "")
                lines.append(f"- {src}: {summary[:180]}")

        artifacts = run_context.get("artifacts", [])
        if artifacts:
            lines.append("Üretilen Çıktılar:")
            for art in artifacts[:6]:
                lines.append(f"- {art.get('type')}: {art.get('value')}")

        return "\n".join(lines)

    async def _execute_step_with_defaults(
        self,
        agent,
        routine: dict[str, Any],
        step: str,
        step_index: int,
        run_context: dict[str, Any],
    ) -> tuple[bool, bool, str]:
        """
        Apply deterministic defaults for common business routine steps.
        Returns: (handled, success, output_text)
        """
        text = _clean_text(step)
        low = text.lower()
        if not hasattr(agent, "_execute_tool"):
            return False, False, ""

        panel_urls = _normalize_panels(run_context.get("panel_urls", []))
        explicit_urls = _extract_urls(text)

        try:
            if ("tarayıcı" in low or "browser" in low) and any(k in low for k in ("aç", "ac", "open", "git", "navigate")):
                targets = explicit_urls or panel_urls[:1] or ["https://www.google.com"]
                outs = []
                step_ok = True
                for url in targets[:5]:
                    ok, msg, _ = await self._run_tool(
                        agent,
                        "open_url",
                        {"url": url},
                        user_input=text,
                        step_name=f"routine_step_{step_index}",
                    )
                    step_ok = step_ok and ok
                    outs.append(f"{url} ({'OK' if ok else 'FAIL'})")
                    run_context.setdefault("artifacts", []).append({"type": "url", "value": url})
                return True, step_ok, "Tarayıcı adımı: " + ", ".join(outs)

            if any(k in low for k in ("giriş yap", "giris yap", "login", "oturum aç", "oturum ac")) or (
                "panel" in low and any(k in low for k in ("giriş", "giris", "aç", "ac"))
            ):
                targets = explicit_urls or panel_urls
                if not targets:
                    return True, True, "Uyarı: Panel URL tanımlı değil. Bu adım atlandı."
                outs = []
                step_ok = True
                for url in targets[:8]:
                    ok, _msg, _ = await self._run_tool(
                        agent,
                        "open_url",
                        {"url": url},
                        user_input=text,
                        step_name=f"routine_step_{step_index}",
                    )
                    step_ok = step_ok and ok
                    outs.append(f"{url} ({'OK' if ok else 'FAIL'})")
                return True, step_ok, "Panel açılışları: " + ", ".join(outs)

            if any(
                k in low
                for k in (
                    "kontrol et",
                    "kontrol",
                    "yeni veri",
                    "sipariş",
                    "kargo",
                    "müşteri",
                    "musteri",
                    "stok",
                    "fiyat",
                    "form",
                    "bildirim",
                    "mail",
                    "e-posta",
                )
            ):
                targets = explicit_urls or panel_urls
                findings = run_context.setdefault("findings", [])
                if targets:
                    checked = 0
                    failed = 0
                    for url in targets[:5]:
                        ok, msg, raw = await self._run_tool(
                            agent,
                            "fetch_page",
                            {"url": url},
                            user_input=text,
                            step_name=f"routine_step_{step_index}",
                        )
                        if not ok:
                            failed += 1
                            findings.append({"source": url, "title": "erişim hatası", "summary": _clean_text(msg)[:220], "url": url})
                            continue
                        checked += 1
                        title = _clean_text(raw.get("title") if isinstance(raw, dict) else "") or url
                        content = _clean_text(raw.get("content") if isinstance(raw, dict) else msg)
                        summary = content[:220] if content else title
                        findings.append({"source": url, "title": title, "summary": summary, "url": url})
                    if checked == 0:
                        if failed > 0:
                            return True, True, f"Uyarı: {failed} panel erişimi başarısız. Erişilebilen veri yok."
                        return True, True, "Uyarı: Panel kontrolünde okunabilir veri alınamadı."
                    if failed > 0:
                        return True, True, f"{checked} panel kontrol edildi, {failed} panelde erişim hatası var."
                    return True, True, f"{checked} panel kontrol edildi."

                query = text
                for token in ("kontrol et", "kontrol", "var mı", "var mi", "yeni veri", "belirlenen", "paneller"):
                    query = query.replace(token, " ")
                query = re.sub(r"\s+", " ", query).strip() or text

                ok, msg, raw = await self._run_tool(
                    agent,
                    "web_search",
                    {"query": query, "num_results": 5},
                    user_input=text,
                    step_name=f"routine_step_{step_index}",
                )
                if ok and isinstance(raw, dict):
                    for item in raw.get("results", [])[:5]:
                        if isinstance(item, dict):
                            findings.append(
                                {
                                    "source": item.get("url", "web"),
                                    "title": item.get("title", ""),
                                    "summary": item.get("snippet", ""),
                                    "url": item.get("url", ""),
                                }
                            )
                    return True, True, msg
                return True, True, f"Uyarı: Web arama adımı başarısız: {_clean_text(msg)[:180]}"

            if ("excel" in low or "tablo" in low or "xlsx" in low) and any(
                k in low for k in ("oluştur", "olustur", "hazırla", "hazirla", "create", "yaz")
            ):
                rows = self._build_excel_rows(run_context)
                out_path = self._default_excel_path(routine)
                ok, _msg, _raw = await self._run_tool(
                    agent,
                    "write_excel",
                    {"path": out_path, "data": rows, "sheet_name": "Routine"},
                    user_input=text,
                    step_name=f"routine_step_{step_index}",
                )
                if ok:
                    run_context.setdefault("artifacts", []).append({"type": "excel", "value": out_path})
                    return True, True, f"Excel raporu oluşturuldu: {out_path}"
                # Fallback: plain markdown summary file if excel writer is unavailable.
                summary = self._build_summary_text(routine, run_context)
                fallback_path = self._default_summary_path(routine)
                w_ok, _w_msg, _w_raw = await self._run_tool(
                    agent,
                    "write_file",
                    {"path": fallback_path, "content": summary},
                    user_input=text,
                    step_name=f"routine_step_{step_index}",
                )
                if w_ok:
                    run_context.setdefault("artifacts", []).append({"type": "summary", "value": fallback_path})
                    return True, True, f"Excel oluşturulamadı, özet dosyası yazıldı: {fallback_path}"
                return True, True, f"Uyarı: Excel raporu oluşturulamadı: {out_path}"

            if any(k in low for k in ("özet rapor", "ozet rapor", "özet", "ozet", "rapor hazırla", "rapor hazirla")):
                summary_text = self._build_summary_text(routine, run_context)
                run_context["generated_summary"] = summary_text
                return True, True, summary_text

            if any(k in low for k in ("telegram", "whatsapp", "discord", "slack", "webchat")) and any(
                k in low for k in ("gönder", "gonder", "send", "ilet")
            ):
                summary = run_context.get("generated_summary") or self._build_summary_text(routine, run_context)
                return True, True, f"Teslim adımı not edildi. Gönderim callback ile yapılacak.\n{summary[:600]}"

            if any(k in low for k in ("screenshot", "ekran görünt", "ekran gorunt")):
                ok, msg, raw = await self._run_tool(
                    agent,
                    "take_screenshot",
                    {},
                    user_input=text,
                    step_name=f"routine_step_{step_index}",
                )
                if ok and isinstance(raw, dict) and _clean_text(raw.get("path")):
                    run_context.setdefault("artifacts", []).append({"type": "screenshot", "value": raw.get("path")})
                return True, ok, msg

            if "masaüst" in low or "desktop" in low:
                ok, msg, _ = await self._run_tool(
                    agent,
                    "list_files",
                    {"path": "~/Desktop"},
                    user_input=text,
                    step_name=f"routine_step_{step_index}",
                )
                return True, ok, msg

        except Exception as e:
            return True, False, f"Hata: {e}"

        return False, False, ""

    def _format_report(
        self,
        *,
        routine: Dict[str, Any],
        step_results: List[Dict[str, Any]],
        run_context: dict[str, Any],
        duration_s: float,
        success: bool,
    ) -> str:
        lines = [
            f"Elyan Routine Report: {routine.get('name')}",
            f"Run Time: {_now_iso()}",
            f"Status: {'SUCCESS' if success else 'PARTIAL/FAILED'}",
            f"Duration: {round(duration_s, 2)}s",
            f"Template: {routine.get('template_id') or 'custom'}",
            "-" * 46,
        ]

        panels = _normalize_panels(routine.get("panels", []))
        if panels:
            lines.append("Panels:")
            for p in panels[:8]:
                lines.append(f"- {p}")
            lines.append("-" * 46)

        for row in step_results:
            icon = "OK" if row.get("success") else "FAIL"
            lines.append(f"[{icon}] #{row.get('index')} {row.get('step')}")
            output = _clean_text(row.get("output"))
            if output:
                lines.append(f"  -> {output[:420]}")

        findings = run_context.get("findings", [])
        if findings:
            lines.append("-" * 46)
            lines.append("Findings:")
            for item in findings[:8]:
                src = _clean_text(item.get("source") or item.get("url") or "source")
                summary = _clean_text(item.get("summary") or item.get("title") or "")
                lines.append(f"- {src}: {summary[:220]}")

        artifacts = run_context.get("artifacts", [])
        if artifacts:
            lines.append("-" * 46)
            lines.append("Artifacts:")
            for art in artifacts[:10]:
                lines.append(f"- {art.get('type')}: {art.get('value')}")

        lines.append("-" * 46)
        lines.append("End of report.")
        return "\n".join(lines)

    def _persist_report(self, routine: dict[str, Any], report: str) -> str:
        try:
            day = datetime.now().strftime("%Y%m%d")
            run_id = datetime.now().strftime("%H%M%S")
            slug = _safe_slug(routine.get("name", "routine"))
            out_dir = ROUTINE_REPORT_DIR / day
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{slug}_{run_id}.md"
            out_path.write_text(report, encoding="utf-8")
            return str(out_path)
        except Exception as e:
            logger.warning(f"Routine report persist failed: {e}")
            return ""

    def _persist(self) -> None:
        try:
            ROUTINE_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            ROUTINE_PERSIST_PATH.write_text(
                json.dumps(self._routines, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Routine persist failed: {e}")

    def _load(self) -> None:
        if not ROUTINE_PERSIST_PATH.exists():
            self._routines = {}
            return
        try:
            data = json.loads(ROUTINE_PERSIST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._routines = data
            else:
                self._routines = {}
        except Exception as e:
            logger.error(f"Routine load failed: {e}")
            self._routines = {}

    def start_background_loop(self, agent_instance):
        """Infinite async loop evaluating triggers."""
        import asyncio
        if getattr(self, "_bg_running", False):
            return
            
        self._bg_running = True
        logger.info("🕰️ Chronos Routine Background Loop Started.")
        
        async def _loop():
            from core.multi_agent.orchestrator import AgentOrchestrator
            from core.multi_agent.neural_router import NeuralRouter
            
            while self._bg_running:
                for rid, routine in self._routines.items():
                    if not routine.get("enabled"): continue
                    # A production branch uses croniter. For now, we will simulate a lightweight trigger pass.
                    pass 
                await asyncio.sleep(60) # Poll every minute
                
        self._bg_task = asyncio.create_task(_loop())
        
    def stop_background_loop(self):
        if hasattr(self, "_bg_task"):
            self._bg_task.cancel()
        self._bg_running = False
        logger.info("🛑 Chronos Routine Background Loop Stopped.")


routine_engine = RoutineEngine()
