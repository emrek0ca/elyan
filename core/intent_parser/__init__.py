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
from core.nlu import get_phase1_engine

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
            self._parse_document_vision,
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
            r"\s*(?:[,;]+\s*|\s+(?:ve\s+sonra|ardından|ardindan|sonra|sonrasında|sonrasinda|then|açıp|acip|çalıştırıp|calistirip|gidip|girip|yazıp|yazip)\s+)\s*",
            re.IGNORECASE,
        )
        self._phase1 = get_phase1_engine()

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
            return self._apply_execution_preferences(coding_intent, original)

        screen_intent = self._parse_screen_workflow(text, text_norm, original)
        if screen_intent:
            return self._apply_execution_preferences(screen_intent, original)

        status_intent = self._parse_status_snapshot(text, text_norm, original)
        if status_intent:
            return self._apply_execution_preferences(status_intent, original)

        phase1 = self._phase1.classify(original, allow_clarify=True) if self._phase1 is not None else None
        phase1_prefetch = self._prefer_phase1_preparse(original, phase1)
        if phase1_prefetch:
            return self._apply_execution_preferences(phase1_prefetch, original)

        multi = self._parse_multi_task(original)
        if multi:
            return self._apply_execution_preferences(multi, original)

        single = self._parse_single(text, text_norm, original)
        if single:
            phase1_override = self._prefer_phase1_override(original, single, phase1)
            if phase1_override:
                return self._apply_execution_preferences(phase1_override, original)
            generic_help_override = self._prefer_generic_help_conversation(original, single)
            if generic_help_override:
                return self._apply_execution_preferences(generic_help_override, original)
            return self._apply_execution_preferences(single, original)

        if phase1:
            payload = self._phase1_payload(original, phase1)
            if payload and payload.get("action") != "chat":
                logger.debug(
                    "[intent_parser] phase1 → %s (intent=%s, confidence=%.2f)",
                    payload.get("action"),
                    phase1.intent,
                    phase1.confidence,
                )
                return self._apply_execution_preferences(payload, original)

        return self._apply_execution_preferences(self._parse_chat_fallback(text, text_norm, original), original)

    def _phase1_payload(self, original: str, phase1: Any) -> dict[str, Any]:
        payload = phase1.to_parser_payload()
        if phase1.intent == "clarify" and self._looks_like_assistance_request(original):
            question = "Tabii, hangi konuda yardımcı olmamı istersin?"
            payload["params"] = {
                **dict(payload.get("params") or {}),
                "question": question,
            }
            payload["reply"] = question
        return payload

    def _prefer_phase1_preparse(self, original: str, phase1: Any) -> dict[str, Any] | None:
        if not phase1:
            return None
        low = original.strip().lower()
        if self._contains_explicit_operator_signal(low) or self._looks_like_task_request(low):
            return None
        if phase1.intent == "chat" and float(phase1.confidence or 0.0) >= 0.9:
            return self._phase1_payload(original, phase1)
        if phase1.intent == "clarify" and phase1.needs_clarification:
            return self._phase1_payload(original, phase1)
        return None

    def _prefer_phase1_override(
        self,
        original: str,
        parsed: dict[str, Any],
        phase1: Any,
    ) -> dict[str, Any] | None:
        if not phase1:
            return None
        parsed_action = str(parsed.get("action") or "").strip().lower()
        if parsed_action != "show_help":
            return None
        if self._contains_explicit_operator_signal(original):
            return None
        if phase1.intent not in {"chat", "clarify"}:
            return None
        return self._phase1_payload(original, phase1)

    def _prefer_generic_help_conversation(self, original: str, parsed: dict[str, Any]) -> dict[str, Any] | None:
        parsed_action = str(parsed.get("action") or "").strip().lower()
        if parsed_action != "show_help":
            return None
        if not self._looks_like_assistance_request(original):
            return None
        return {
            "action": "clarify",
            "params": {"question": "Tabii, hangi konuda yardımcı olmamı istersin?"},
            "reply": "Tabii, hangi konuda yardımcı olmamı istersin?",
            "confidence": 0.82,
        }

    def _contains_explicit_operator_signal(self, text: str) -> bool:
        low = str(text or "").strip().lower()
        signals = (
            "aç", "ac", "kapat", "oluştur", "olustur", "sil", "delete", "write",
            "yaz", "araştır", "arastir", "search", "listele", "oku", "kaydet",
            "çalıştır", "calistir", "run", "open", "close", "gönder", "gonder",
            "click", "tıkla", "tikla", "planla", "uygula", "build", "create",
        )
        return any(signal in low for signal in signals)

    def _looks_like_assistance_request(self, text: str) -> bool:
        low = str(text or "").strip().lower()
        markers = (
            "yardım", "yardim", "yardımcı", "yardimci", "help", "assist",
            "bir şey soracağım", "bir sey soracagim", "soru soracağım", "soru soracagim",
        )
        return any(marker in low for marker in markers)

    def _looks_like_task_request(self, text: str) -> bool:
        low = str(text or "").strip().lower()
        markers = (
            "sistem", "system", "ekran", "screen", "screenshot", "dosya", "file",
            "klasör", "klasor", "folder", "masaüst", "desktop", "takvim", "calendar",
            "mail", "gmail", "browser", "tarayıcı", "tarayici", "chrome", "safari",
            "notion", "whatsapp", "telegram", "pdf", "word", "excel", "sunum",
            "kod", "code", "terminal", "komut", "command", "araştır", "arastir",
            "web", "site", "uygulama", "application",
        )
        return any(marker in low for marker in markers)

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
        if any(
            marker in original.lower()
            for marker in (
                "layout",
                "ocr",
                "tablo",
                "table",
                "chart",
                "grafik",
                "diagram",
                "figure",
                "vision",
                "görsel",
                "gorsel",
            )
        ):
            document_vision = self._parse_document_vision(original.lower(), self._normalize(original), original)
            if document_vision:
                return document_vision

        normalized = re.sub(r"\baçıp\b", "aç sonra", original, flags=re.IGNORECASE)
        normalized = re.sub(r"\bacip\b", "aç sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bçalıştırıp\b", "çalıştır sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bcalistirip\b", "çalıştır sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bgidip\b", "git sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bgirip\b", "gir sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\byazıp\b", "yaz sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\byazip\b", "yaz sonra", normalized, flags=re.IGNORECASE)
        parts = [p.strip() for p in self._multi_split_re.split(normalized) if p.strip()]
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

        # Terminal odaklı ardışık komutlarda ikinci adımı UI üzerinden çalıştır:
        # "terminal aç ve X komutunu çalıştır" -> open_app(Terminal) + type_text(enter)
        for idx in range(1, len(tasks)):
            prev = tasks[idx - 1] if isinstance(tasks[idx - 1], dict) else {}
            cur = tasks[idx] if isinstance(tasks[idx], dict) else {}
            prev_action = str(prev.get("action") or "").strip().lower()
            cur_action = str(cur.get("action") or "").strip().lower()
            prev_app = str((prev.get("params") or {}).get("app_name") or "").strip().lower()
            if prev_action == "open_app" and prev_app == "terminal" and cur_action == "run_safe_command":
                cmd = str((cur.get("params") or {}).get("command") or "").strip()
                if not cmd:
                    continue
                cur["action"] = "type_text"
                cur["params"] = {"text": cmd, "press_enter": True}
                cur["description"] = "Komut terminalde çalıştırılıyor..."

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
