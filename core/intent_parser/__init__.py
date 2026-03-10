"""
core/intent_parser/__init__.py
Ana IntentParser sınıfı — tüm alt modülleri miras alır.
BUG-FUNC-004: 100KB tek dosya → modüler paket yapısına bölündü.
"""
from __future__ import annotations
import re
from typing import Any

from ._base import BaseParser
from ._system import SystemParser
from ._apps import AppParser
from ._files import FileParser
from ._research import ResearchParser
from ._documents import DocumentParser
from ._media import MediaParser
from ._free_apis import FreeApiParser

from utils.logger import get_logger

logger = get_logger("intent_parser")


class IntentParser(
    SystemParser,
    AppParser,
    FileParser,
    ResearchParser,
    DocumentParser,
    MediaParser,
    FreeApiParser,
):
    """
    Elyan Intent Parser — Türkçe/İngilizce doğal dil anlama motoru.

    Modüler yapı (BUG-FUNC-004):
    ├── _base.py        → alias tabloları, compiled regex, yardımcı metodlar
    ├── _system.py      → screenshot, volume, brightness, wifi, power, clipboard
    ├── _apps.py        → open/close app, URL, browser search, YouTube, greeting
    ├── _files.py       → create_folder, list_files, write_file, search_files
    ├── _research.py    → research, web_search, summarize, translate
    ├── _documents.py   → Word, Excel, PDF, website, presentation
    └── _media.py       → email, calendar, reminder, music, code_run, help
    """

    def __init__(self):
        super().__init__()
        # Parser pipeline — sıralı, ilk eşleşen kazanır
        self._pipeline = [
            # Dashboard drop (yüksek öncelik)
            self._parse_dropped_file,
            # Sistem kontrolleri (yüksek öncelik)
            self._parse_screen_workflow,
            self._parse_screenshot,
            self._parse_status_snapshot,
            self._parse_volume,
            self._parse_brightness,
            self._parse_dark_mode,
            self._parse_wifi,
            self._parse_power_control,
            self._parse_clipboard,
            self._parse_notification,
            self._parse_input_control,
            self._parse_system_info,
            self._parse_process_control,
            self._parse_weather,
            # Uygulama / URL
            self._parse_greeting,
            self._parse_media_play,          # YouTube (URL'den önce)
            self._parse_random_image,
            self._parse_browser_tab_control,
            self._parse_open_url,
            self._parse_browser_search,
            self._parse_open_app,
            self._parse_close_app,
            self._parse_spotlight,
            self._parse_terminal_command,
            # Dosya sistemi
            self._parse_create_folder,
            self._parse_list_files,
            self._parse_write_file,
            self._parse_search_files,
            self._parse_read_file,
            self._parse_delete_file,
            # Araştırma / web
            self._parse_research,
            self._parse_web_search,
            self._parse_summarize,
            self._parse_translate,
            # Belgeler
            self._parse_create_coding_project,
            self._parse_create_website,
            self._parse_create_word,
            self._parse_create_excel,
            self._parse_pdf_operations,
            self._parse_create_presentation,
            # Medya / iletişim
            self._parse_email,
            self._parse_calendar,
            self._parse_reminder,
            self._parse_music,
            self._parse_code_run,
            self._parse_code_write,
            self._parse_visual_generation,
            self._parse_scheduled_tasks,
            self._parse_help,
            # Ücretsiz API Parser'ları (en düşük öncelik)
            self._parse_crypto,
            self._parse_exchange_rate,
            self._parse_weather_city,
            self._parse_wikipedia,
            self._parse_dictionary,
            self._parse_country_info,
            self._parse_ddg_search,
            self._parse_academic_search,
            self._parse_random_content,
        ]
        self._multi_split_re = re.compile(
            r"\s*(?:[,;]+\s*|\s+(?:ve\s+sonra|ardından|ardindan|sonra|sonrasında|sonrasinda|then)\s+)\s*",
            re.IGNORECASE,
        )

    # ── Public API ────────────────────────────────────────────────────────────
    def parse(self, text: str) -> dict[str, Any]:
        """
        Metni parse eder ve action dict döner.

        Returns:
            {
                "action": str,
                "params": dict,
                "reply": str,
                "confidence": float,
            }
        """
        if not text or not text.strip():
            return self._parse_chat_fallback("", "", "")

        original = text.strip()
        text = original.lower()
        text_norm = self._normalize(text)

        coding_intent = self._parse_create_coding_project(text, text_norm, original)
        if coding_intent:
            return coding_intent

        screen_intent = self._parse_screen_workflow(text, text_norm, original)
        if screen_intent:
            return screen_intent

        status_intent = self._parse_status_snapshot(text, text_norm, original)
        if status_intent:
            return status_intent

        multi = self._parse_multi_task(original)
        if multi:
            return multi

        single = self._parse_single(text, text_norm, original)
        if single:
            return single

        return self._parse_chat_fallback(text, text_norm, original)

    def _parse_single(self, text: str, text_norm: str, original: str) -> dict[str, Any] | None:
        for parser_fn in self._pipeline:
            try:
                result = parser_fn(text, text_norm, original)
                if result:
                    result.setdefault("confidence", 0.85)
                    logger.debug(f"[intent_parser] {parser_fn.__name__} → {result['action']}")
                    return result
            except Exception as exc:
                logger.warning(f"[intent_parser] {parser_fn.__name__} hata: {exc}")
                continue
        return None

    def _parse_multi_task(self, original: str) -> dict[str, Any] | None:
        """
        Basit çok-adımlı cümleleri (ve sonra / ardından) tek plana dönüştür.
        """
        parts = [p.strip() for p in self._multi_split_re.split(original) if p.strip()]
        if len(parts) < 2 and " ve " in original.lower():
            # Plain "ve" fallback only when both sides look action-like.
            raw_parts = [p.strip() for p in re.split(r"\s+ve\s+", original, flags=re.IGNORECASE) if p.strip()]
            action_like = 0
            for p in raw_parts:
                if self._looks_like_action_segment(p):
                    action_like += 1
            if action_like >= 2:
                parts = raw_parts
        if len(parts) < 2:
            return None

        tasks: list[dict[str, Any]] = []
        for i, part in enumerate(parts, start=1):
            part_text = part.lower()
            parsed = self._parse_single(part_text, self._normalize(part_text), part)
            if not parsed:
                return None
            action = str(parsed.get("action", "")).strip()
            if not action or action in {"chat", "unknown", "multi_task"}:
                return None

            task: dict[str, Any] = {
                "id": f"task_{i}",
                "action": action,
                "params": parsed.get("params", {}) if isinstance(parsed.get("params"), dict) else {},
                "description": parsed.get("reply", part),
            }
            if i > 1:
                task["depends_on"] = [f"task_{i-1}"]
            tasks.append(task)

        if len(tasks) < 2:
            return None
        return {
            "action": "multi_task",
            "tasks": tasks,
            "reply": "Çok adımlı görev planlandı ve sırayla çalıştırılacak.",
            "confidence": 0.9,
        }

    def _looks_like_action_segment(self, segment: str) -> bool:
        raw = str(segment or "").strip()
        if len(raw) < 3:
            return False
        low = raw.lower()
        action_verbs = (
            "aç", "ac", "kapat", "araştır", "arastir", "ara", "search", "kaydet",
            "yaz", "oluştur", "olustur", "listele", "göster", "goster", "oku",
            "çevir", "cevir", "özetle", "ozetle", "hatırlat", "hatirlat",
        )
        if any(v in low for v in action_verbs):
            return True
        parsed = self._parse_single(low, self._normalize(low), raw)
        if not parsed:
            return False
        action = str(parsed.get("action", "") or "").strip().lower()
        return bool(action and action not in {"chat", "unknown", "multi_task"})

    def parse_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """Toplu parse — birden fazla mesaj için"""
        return [self.parse(t) for t in texts]

    def get_action(self, text: str) -> str:
        """Sadece action adını döner"""
        return self.parse(text).get("action", "chat")

    def get_params(self, text: str) -> dict:
        """Sadece params'ı döner"""
        return self.parse(text).get("params", {})


# ── Singleton ─────────────────────────────────────────────────────────────────
_parser_instance: IntentParser | None = None


def get_intent_parser() -> IntentParser:
    """Global singleton — her seferinde yeni instance oluşturmaz"""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = IntentParser()
    return _parser_instance


# ── Backward compat ───────────────────────────────────────────────────────────
__all__ = ["IntentParser", "get_intent_parser"]
