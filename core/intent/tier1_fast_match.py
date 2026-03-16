"""
Tier 1: Fast Exact/Fuzzy Matching (< 2ms)

Hardcoded exact patterns and fuzzy matching for common intents.
Handles ~40% of traffic with high confidence (0.95-0.99).
"""

import re
from difflib import SequenceMatcher
from typing import Optional, Tuple, Dict, List
from utils.logger import get_logger
from .models import IntentCandidate, IntentConfidence

logger = get_logger("tier1_fast_match")

# Tier 1 Fast Match Database - Exact and fuzzy patterns
FAST_MATCH_DB = {
    # Screenshots & Capture
    "screenshot": {
        "patterns": ["screenshot", "ss", "ssot", "resim çek", "görüntü al", "ekran al"],
        "tool": "take_screenshot",
        "params": {},
        "confidence": 0.99
    },
    "record_screen": {
        "patterns": ["record screen", "record", "kayıt yap", "ekran kaydet", "video çek"],
        "tool": "record_screen",
        "params": {},
        "confidence": 0.98
    },

    # Volume Control
    "mute": {
        "patterns": ["sesi kapat", "sustur", "mute", "sesi aç kapı", "sıfırla ses", "ses kapat"],
        "tool": "set_volume",
        "params": {"volume": 0},
        "confidence": 0.99
    },
    "max_volume": {
        "patterns": ["ses aç", "sesi aç", "maximum ses", "en yüksek", "full volume", "100"],
        "tool": "set_volume",
        "params": {"volume": 100},
        "confidence": 0.99
    },
    "volume_50": {
        "patterns": ["orta ses", "medium volume", "yarısı", "50"],
        "tool": "set_volume",
        "params": {"volume": 50},
        "confidence": 0.98
    },

    # Greeting & Chat
    "greeting": {
        "patterns": ["merhaba", "selam", "hi", "hello", "hey", "sabahın hayırı", "iyi günler"],
        "tool": "chat",
        "params": {},
        "confidence": 0.99
    },
    "goodbye": {
        "patterns": ["hoşça kalın", "goodbye", "bye", "hoşça", "güle güle", "see you"],
        "tool": "chat",
        "params": {},
        "confidence": 0.99
    },

    # Time & Date
    "what_time": {
        "patterns": ["saat kaç", "what time", "current time", "şu anki saat", "zaman"],
        "tool": "chat",
        "params": {},
        "confidence": 0.99
    },
    "what_date": {
        "patterns": ["bugün kaç", "today", "today's date", "tarihi söyle", "bugünün tarihi"],
        "tool": "chat",
        "params": {},
        "confidence": 0.99
    },

    # File Operations
    "list_files": {
        "patterns": ["dosyaları listele", "list files", "ls", "ls -la", "what files", "hangi dosyalar"],
        "tool": "list_files",
        "params": {},
        "confidence": 0.98
    },
    "open_file_explorer": {
        "patterns": ["dosya aç", "open file", "finder", "dosya yöneticisi", "explorer aç"],
        "tool": "open_file_explorer",
        "params": {},
        "confidence": 0.97
    },

    # App Control
    "open_browser": {
        "patterns": ["tarayıcı aç", "open browser", "chrome", "firefox", "safari"],
        "tool": "open_app",
        "params": {"app_name": "browser"},
        "confidence": 0.97
    },
    "open_terminal": {
        "patterns": ["terminal aç", "open terminal", "cmd", "command prompt", "bash"],
        "tool": "open_terminal",
        "params": {},
        "confidence": 0.98
    },
    "open_settings": {
        "patterns": ["ayarlar aç", "open settings", "preferences", "system preferences"],
        "tool": "open_settings",
        "params": {},
        "confidence": 0.97
    },

    # Power Control
    "lock_screen": {
        "patterns": ["ekranı kilitle", "lock screen", "lock", "sleep", "uyut"],
        "tool": "lock_screen",
        "params": {},
        "confidence": 0.98
    },
    "shutdown": {
        "patterns": ["kapat", "shutdown", "power off", "exit", "çık"],
        "tool": "system_shutdown",
        "params": {},
        "confidence": 0.95
    },

    # Notification & Chat
    "send_notification": {
        "patterns": ["bildirim gönder", "notification", "notify", "alert"],
        "tool": "send_notification",
        "params": {},
        "confidence": 0.96
    },
    "send_message": {
        "patterns": ["mesaj gönder", "send message", "text", "sms"],
        "tool": "send_message",
        "params": {},
        "confidence": 0.96
    },

    # Help & Info
    "help": {
        "patterns": ["yardım", "help", "ne yapabilirsin", "capabilities", "what can you do"],
        "tool": "chat",
        "params": {},
        "confidence": 0.99
    },
}


class FastMatcher:
    """Exact and fuzzy pattern matching for quick intent recognition."""

    def __init__(self):
        self.db = FAST_MATCH_DB
        self._build_lookup()

    def _build_lookup(self) -> None:
        """Build optimized lookup tables."""
        self.exact_lookup: Dict[str, str] = {}  # pattern -> db_key
        for key, entry in self.db.items():
            for pattern in entry.get("patterns", []):
                normalized = pattern.lower().strip()
                self.exact_lookup[normalized] = key

    def match(self, user_input: str) -> Optional[IntentCandidate]:
        """
        Attempt fast match: exact → fuzzy → substring.

        Args:
            user_input: User's message

        Returns:
            IntentCandidate with high confidence, or None
        """
        normalized = user_input.lower().strip()

        # Try exact match first
        if normalized in self.exact_lookup:
            key = self.exact_lookup[normalized]
            return self._create_candidate(key, 0.99, "exact_match")

        # Try fuzzy match (Levenshtein-like with SequenceMatcher)
        best_match = self._fuzzy_match(normalized)
        if best_match:
            return best_match

        # Try substring match (full pattern in user input)
        substring_match = self._substring_match(normalized)
        if substring_match:
            return substring_match

        return None

    def _fuzzy_match(self, normalized: str, threshold: float = 0.80) -> Optional[IntentCandidate]:
        """Fuzzy match with SequenceMatcher."""
        best_key = None
        best_ratio = 0.0

        for key, entry in self.db.items():
            for pattern in entry.get("patterns", []):
                pattern_normalized = pattern.lower().strip()
                ratio = SequenceMatcher(None, normalized, pattern_normalized).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_key = key

        if best_key and best_ratio >= threshold:
            # Scale confidence: 0.80-0.95 ratio maps to 0.80-0.95 confidence
            confidence = 0.80 + (best_ratio - threshold) * 0.15 / (1.0 - threshold)
            confidence = min(0.95, max(0.80, confidence))
            return self._create_candidate(best_key, confidence, "fuzzy_match")

        return None

    def _substring_match(self, normalized: str) -> Optional[IntentCandidate]:
        """Match if user input contains full pattern."""
        for key, entry in self.db.items():
            for pattern in entry.get("patterns", []):
                pattern_normalized = pattern.lower().strip()
                if pattern_normalized in normalized and len(pattern_normalized) > 3:
                    # Only match if pattern is reasonably long and specific
                    return self._create_candidate(key, 0.85, "substring_match")

        return None

    def _create_candidate(self, key: str, confidence: float, method: str) -> IntentCandidate:
        """Create IntentCandidate from DB entry."""
        entry = self.db[key]
        return IntentCandidate(
            action=entry["tool"],
            confidence=confidence,
            reasoning=f"Tier 1 {method}: '{entry['patterns'][0]}'",
            params=entry.get("params", {}),
            source_tier="tier1",
            metadata={"match_method": method, "db_key": key}
        )

    def get_pattern_count(self) -> int:
        """Get total number of patterns in Tier 1 DB."""
        return sum(len(entry.get("patterns", [])) for entry in self.db.values())

    def add_pattern(self, db_key: str, pattern: str, overwrite: bool = False) -> bool:
        """
        Add pattern to Tier 1 DB (for learning).

        Args:
            db_key: Key in FAST_MATCH_DB
            pattern: Pattern to add
            overwrite: If True, create new entry

        Returns:
            True if added successfully
        """
        if db_key not in self.db and not overwrite:
            return False

        if db_key not in self.db:
            self.db[db_key] = {
                "patterns": [],
                "tool": "",
                "params": {},
                "confidence": 0.90
            }

        normalized = pattern.lower().strip()
        if normalized not in self.db[db_key]["patterns"]:
            self.db[db_key]["patterns"].append(normalized)
            # Rebuild lookup
            self._build_lookup()
            return True

        return False
