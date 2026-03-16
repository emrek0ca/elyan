"""
Intent Disambiguator

When multiple candidates have similar confidence, present options to user.
Learn from user choice.
"""

from typing import List, Dict, Any, Optional
from utils.logger import get_logger
from .models import IntentCandidate

logger = get_logger("intent_disambiguator")


class IntentDisambiguator:
    """Handle ambiguous intents with user feedback."""

    @staticmethod
    def needs_disambiguation(candidates: List[IntentCandidate], threshold: float = 0.1) -> bool:
        """
        Check if candidates are ambiguous (similar confidence).

        Args:
            candidates: List of candidates
            threshold: Confidence difference threshold

        Returns:
            True if disambiguation needed
        """
        if len(candidates) < 2:
            return False

        best_conf = candidates[0].confidence
        second_best_conf = candidates[1].confidence
        return abs(best_conf - second_best_conf) <= threshold

    @staticmethod
    def create_disambiguation_dialog(candidates: List[IntentCandidate]) -> Dict[str, Any]:
        """
        Create disambiguation dialog.

        Args:
            candidates: Ambiguous candidates

        Returns:
            Dialog dict with options
        """
        options = []
        for i, candidate in enumerate(candidates[:5], 1):  # Max 5 options
            options.append({
                "id": i,
                "action": candidate.action,
                "confidence": candidate.confidence,
                "reasoning": candidate.reasoning,
                "description": IntentDisambiguator._describe_action(candidate.action)
            })

        return {
            "type": "disambiguation",
            "message": "Neyi yapmak istediğiniz konusunda emin değilim. Lütfen seçin:",
            "options": options
        }

    @staticmethod
    def _describe_action(action: str) -> str:
        """Get user-friendly description of action."""
        descriptions = {
            "take_screenshot": "Ekran görüntüsü al",
            "record_screen": "Ekran kaydı yap",
            "set_volume": "Sesi ayarla",
            "chat": "Sohbet et",
            "list_files": "Dosyaları listele",
            "open_file_explorer": "Dosya yöneticisini aç",
            "open_app": "Uygulama aç",
            "open_terminal": "Terminal aç",
            "lock_screen": "Ekranı kilitle",
            "system_shutdown": "Bilgisayarı kapat",
            "send_notification": "Bildirim gönder",
            "send_message": "Mesaj gönder",
            "multi_task": "Çoklu görev yap",
            "clarify": "Soruyla devam et"
        }
        return descriptions.get(action, action)

    @staticmethod
    def handle_user_choice(choice_id: int, candidates: List[IntentCandidate]) -> Optional[IntentCandidate]:
        """
        Handle user's disambiguation choice.

        Args:
            choice_id: Selected option ID (1-based)
            candidates: Original candidates

        Returns:
            Selected candidate with adjusted confidence
        """
        if 0 < choice_id <= len(candidates):
            candidate = candidates[choice_id - 1]
            # Boost confidence since user confirmed
            candidate.confidence = min(1.0, candidate.confidence + 0.15)
            candidate.metadata["user_confirmed"] = True
            return candidate

        return None

    @staticmethod
    def format_options_for_display(candidates: List[IntentCandidate]) -> str:
        """Format candidates as user-readable options."""
        lines = []
        for i, c in enumerate(candidates[:5], 1):
            desc = IntentDisambiguator._describe_action(c.action)
            lines.append(f"{i}. {desc} ({c.confidence:.0%} güven)")

        return "\n".join(lines)
