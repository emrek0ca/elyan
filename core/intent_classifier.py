"""Fast Intent Classifier - Quick classification without full LLM call"""

import re
from typing import Any
from utils.logger import get_logger

logger = get_logger("intent_classifier")


class IntentClassifier:
    """Fast intent classification using pattern matching and keyword detection"""

    def __init__(self):
        # Action categories with keywords
        self.categories = {
            "file_operation": {
                "keywords": ["dosya", "klasör", "folder", "file", "oku", "yaz", "sil",
                           "oluştur", "listele", "göster", "kaydet", "delete", "create"],
                "actions": ["list_files", "read_file", "write_file", "delete_file", "search_files"]
            },
            "app_control": {
                "keywords": ["aç", "kapat", "başlat", "sonlandır", "uygulama", "app",
                           "open", "close", "quit", "run", "start"],
                "actions": ["open_app", "close_app", "open_url", "kill_process"]
            },
            "system": {
                "keywords": ["sistem", "cpu", "ram", "bellek", "disk", "pil", "system",
                           "battery", "memory", "performans"],
                "actions": ["get_system_info", "get_process_info"]
            },
            "media": {
                "keywords": ["ses", "volume", "screenshot", "ekran", "görüntü", "pano",
                           "clipboard", "kopyala", "yapıştır"],
                "actions": ["set_volume", "take_screenshot", "read_clipboard", "write_clipboard"]
            },
            "macos": {
                "keywords": ["karanlık", "dark", "wifi", "bluetooth", "takvim", "calendar",
                           "hatırlat", "reminder", "spotlight", "ara"],
                "actions": ["toggle_dark_mode", "wifi_toggle", "wifi_status",
                          "get_today_events", "create_event", "get_reminders",
                          "create_reminder", "spotlight_search"]
            },
            "office": {
                "keywords": ["word", "excel", "pdf", "docx", "xlsx", "belge", "document",
                           "tablo", "özet", "özetle", "summarize"],
                "actions": ["read_word", "write_word", "read_excel", "write_excel",
                          "read_pdf", "get_pdf_info", "summarize_document"]
            },
            "notification": {
                "keywords": ["bildirim", "notification", "uyarı", "alert", "notify"],
                "actions": ["send_notification"]
            },
            "greeting": {
                "keywords": ["merhaba", "selam", "hey", "hi", "hello", "günaydın",
                           "iyi günler", "nasılsın"],
                "actions": ["chat"]
            }
        }

        # High confidence patterns (regex based)
        self.patterns = {
            r'(masaüstü|masaustu|desktop|desktop klasör|desktop klasor|belgeler|documents).*?(ne var|neler var|göster|goster|listele|contents|içerik|icerik)': "list_files",
            r'(safari|chrome|finder|terminal|vscode).*?(aç|kapat)': "app_open_close",
            r'(ekran|screenshot).*?(al|çek|görüntü)': "take_screenshot",
            r'ses.*?(kapat|aç|%\d+|\d+\s*yap)': "set_volume",
            r'(karanlık|dark).*?(mod|mode|tema)': "toggle_dark_mode",
            r'wifi.*?(kapat|aç|durum)': "wifi_action",
            r'\.(docx|doc)\b': "word_document",
            r'\.(xlsx|xls)\b': "excel_document",
            r'\.pdf\b': "pdf_document",
            r'(bugün|takvim).*?(etkinlik|toplantı)': "calendar",
            r'(hatırlat|anımsat|reminder)': "reminder",
        }

    def classify(self, text: str) -> dict[str, Any]:
        """
        Quickly classify the intent category and confidence

        Returns:
            dict with:
                - category: The detected category
                - confidence: Confidence score (0-1)
                - suggested_actions: List of likely actions
                - needs_llm: Whether full LLM processing is recommended
        """
        text_lower = text.lower()

        # Check high-confidence patterns first
        for pattern, intent in self.patterns.items():
            if re.search(pattern, text_lower):
                category = self._get_category_for_intent(intent)
                return {
                    "category": category,
                    "confidence": 0.9,
                    "suggested_actions": self.categories.get(category, {}).get("actions", []),
                    "needs_llm": False,
                    "pattern_match": intent
                }

        # Keyword-based classification
        category_scores = {}
        for category, data in self.categories.items():
            score = sum(1 for kw in data["keywords"] if kw in text_lower)
            if score > 0:
                category_scores[category] = score

        if category_scores:
            best_category = max(category_scores, key=category_scores.get)
            max_score = category_scores[best_category]
            total_keywords = len(self.categories[best_category]["keywords"])

            confidence = min(max_score / 3, 1.0)  # Normalize to 0-1

            return {
                "category": best_category,
                "confidence": round(confidence, 2),
                "suggested_actions": self.categories[best_category]["actions"],
                "needs_llm": confidence < 0.5,
                "keyword_matches": max_score
            }

        # No clear category
        return {
            "category": "unknown",
            "confidence": 0.0,
            "suggested_actions": [],
            "needs_llm": True,
            "pattern_match": None
        }

    def _get_category_for_intent(self, intent: str) -> str:
        """Map pattern intent to category"""
        mapping = {
            "list_files": "file_operation",
            "app_open_close": "app_control",
            "take_screenshot": "media",
            "set_volume": "media",
            "toggle_dark_mode": "macos",
            "wifi_action": "macos",
            "word_document": "office",
            "excel_document": "office",
            "pdf_document": "office",
            "calendar": "macos",
            "reminder": "macos",
        }
        return mapping.get(intent, "unknown")

    def is_simple_query(self, text: str) -> bool:
        """Check if the query is simple enough to skip LLM"""
        result = self.classify(text)
        return result["confidence"] >= 0.7 and not result["needs_llm"]

    def get_quick_action(self, text: str) -> str | None:
        """
        Try to determine the exact action without LLM

        Returns action name or None if uncertain
        """
        classification = self.classify(text)

        if classification["confidence"] >= 0.8:
            actions = classification["suggested_actions"]
            if len(actions) == 1:
                return actions[0]

            # More specific matching
            text_lower = text.lower()

            # File operations
            if "file_operation" == classification["category"]:
                if any(w in text_lower for w in ["listele", "göster", "ne var"]):
                    return "list_files"
                if any(w in text_lower for w in ["oku", "read"]):
                    return "read_file"
                if any(w in text_lower for w in ["yaz", "oluştur", "kaydet"]):
                    return "write_file"
                if any(w in text_lower for w in ["sil", "delete"]):
                    return "delete_file"
                if any(w in text_lower for w in ["ara", "bul", "search"]):
                    return "search_files"

            # App control
            if "app_control" == classification["category"]:
                if any(w in text_lower for w in ["kapat", "close", "quit"]):
                    return "close_app"
                if any(w in text_lower for w in ["aç", "open", "başlat"]):
                    if "http" in text_lower or ".com" in text_lower:
                        return "open_url"
                    return "open_app"

        return None


# Global classifier instance
_classifier_instance = None


def get_classifier() -> IntentClassifier:
    """Get the global classifier instance"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = IntentClassifier()
    return _classifier_instance
