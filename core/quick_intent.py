"""
Quick Intent Detector
Lightweight intent detection for fast routing
"""

import re
import time
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("quick_intent")


class IntentCategory(Enum):
    """Intent categories"""
    GREETING = "greeting"
    CHAT = "chat"
    QUESTION = "question"
    COMMAND = "command"
    RESEARCH = "research"
    CODING = "coding"
    FILE_OP = "file_operation"
    CALCULATION = "calculation"
    UNKNOWN = "unknown"


@dataclass
class QuickIntent:
    """Quick intent detection result"""
    category: IntentCategory
    confidence: float
    requires_llm: bool
    estimated_complexity: str  # trivial, simple, moderate, complex
    detection_time: float


class QuickIntentDetector:
    """
    Quick Intent Detector
    - Lightweight pattern matching
    - Fast intent classification
    - No LLM calls
    - Sub-10ms detection
    """

    def __init__(self):
        # Pattern definitions
        self.patterns = {
            IntentCategory.GREETING: [
                r'\b(merhaba|selam|hey|hi|hello|günaydın|iyi akşamlar)\b',
            ],
            IntentCategory.CHAT: [
                r'^(iyiyim|kotuyum|kötüyüm|idare|fena degil|fena değil|soyle boyle|şöyle böyle|super|süper|harika)',
                r'^(tesekkur|teşekkür|sagol|sağol|eyvallah|tsk|tşk|tmm|tamam|ok|peki|anladim|anladım)',
                r'^(guzel|güzel|iyi|kotu|kötü|hos|hoş|haklisin|haklısın|dogru|doğru|evet|hayir|hayır|yok)',
                r'^(sen nasilsin|sen nasılsın|ne yapiyorsun|ne yapıyorsun|naber|nasilsin|nasılsın)',
                r'^(gorusuruz|görüşürüz|hosca kal|hoşça kal|bay bay|bb|bye|iyi geceler|iyi gunler|iyi günler)',
                r'^(haha|lol|cok komik|çok komik|guldum|güldüm|bravo|aferin)',
                r'^(ben de|bende|aynen|kesinlikle|tabii|tabi)',
                r'^(hmm|himm|hımm|sey|şey|valla|vallahi|yani)',
                r'^(olsun|bosver|boşver|neyse|gecelim|geçelim)',
            ],
            IntentCategory.COMMAND: [
                r'^/(status|help|stats|cancel|reset|screenshot)',
                r'\b(ekran görüntüsü|screenshot)\b',
                r'\bses[ie]?\s*(kapat|aç|kıs|yükselt|azalt|artır|düşür)\b',
                r'\b(volume|mute|unmute|sessize)\b',
                r'\bparlaklı[kğ]',
                r'\b(wifi|bluetooth)\s*(aç|kapat|durumu?)\b',
                r'\bdark\s*mode\b',
            ],
            IntentCategory.RESEARCH: [
                r'\b(araştır|araştırma|research|inceleme|rapor|report)\b',
            ],
            IntentCategory.CODING: [
                r'\b(kod|code|function|class|script|program|python|javascript)\b',
                r'\b(yaz|write|oluştur|create|düzenle|edit)\s+(kod|code|function)',
            ],
            IntentCategory.FILE_OP: [
                r'\b(dosya|file|klasör|folder)\b',
                r'\b(oku|read|yaz|write|sil|delete|bul|find)\s+(dosya|file)',
            ],
            IntentCategory.CALCULATION: [
                r'\d+\s*[\+\-\*\/]\s*\d+',
                r'\b(hesapla|calculate|toplam|sum)\b',
            ],
            IntentCategory.QUESTION: [
                r'\b(ne|nedir|nasıl|neden|kim|where|what|how|why|when)\b',
                r'\?$',  # Ends with question mark
            ],
        }

        # LLM requirement rules
        self.llm_required = {
            IntentCategory.GREETING: False,
            IntentCategory.CHAT: True,  # Needs LLM but lightweight chat()
            IntentCategory.COMMAND: False,
            IntentCategory.CALCULATION: False,
            IntentCategory.QUESTION: True,
            IntentCategory.RESEARCH: True,
            IntentCategory.CODING: True,
            IntentCategory.FILE_OP: True,
            IntentCategory.UNKNOWN: True,
        }

        # Complexity estimation
        self.complexity_rules = {
            IntentCategory.GREETING: "trivial",
            IntentCategory.CHAT: "trivial",
            IntentCategory.COMMAND: "trivial",
            IntentCategory.CALCULATION: "trivial",
            IntentCategory.QUESTION: "simple",
            IntentCategory.FILE_OP: "simple",
            IntentCategory.CODING: "moderate",
            IntentCategory.RESEARCH: "complex",
            IntentCategory.UNKNOWN: "simple",
        }

        # Pre-compute ASCII-normalized patterns for Turkish text matching
        self.patterns_ascii = {}
        for category, pats in self.patterns.items():
            self.patterns_ascii[category] = [self._normalize_tr(p) for p in pats]

        # Stats
        self.stats = {
            "total_detections": 0,
            "avg_detection_time": 0.0,
            "by_category": {}
        }

        logger.info("Quick Intent Detector initialized")

    @staticmethod
    def _normalize_tr(text: str) -> str:
        tr_map = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
        return text.translate(tr_map)

    def detect(self, text: str) -> QuickIntent:
        """Detect intent quickly"""
        start_time = time.time()

        text_lower = text.lower().strip()
        # Also try ASCII-normalized version for matching
        text_ascii = self._normalize_tr(text_lower)

        # Try each category
        best_category = IntentCategory.UNKNOWN
        best_confidence = 0.0

        for category, patterns in self.patterns.items():
            # Try both original and ASCII-normalized text+patterns
            confidence = max(
                self._match_patterns(text_lower, patterns),
                self._match_patterns(text_ascii, self.patterns_ascii[category]),
            )
            if confidence > best_confidence:
                best_confidence = confidence
                best_category = category

        # Determine if LLM is required
        requires_llm = self.llm_required.get(best_category, True)

        # Adjust for simple questions that might not need LLM
        if best_category == IntentCategory.QUESTION:
            # Check if it's a very simple question
            if len(text.split()) < 5 and any(word in text_lower for word in ['ne', 'nedir', 'what is']):
                requires_llm = False  # Can be answered by fast response system
                best_confidence = min(best_confidence, 0.7)

        # Get complexity estimate
        complexity = self.complexity_rules.get(best_category, "simple")

        detection_time = time.time() - start_time

        # Update stats
        self.stats["total_detections"] += 1
        self.stats["by_category"][best_category.value] = \
            self.stats["by_category"].get(best_category.value, 0) + 1

        # Update average detection time
        total = self.stats["total_detections"]
        old_avg = self.stats["avg_detection_time"]
        self.stats["avg_detection_time"] = (old_avg * (total - 1) + detection_time) / total

        logger.debug(
            f"Quick intent: {best_category.value} "
            f"(confidence={best_confidence:.2f}, "
            f"llm={requires_llm}, "
            f"time={detection_time*1000:.1f}ms)"
        )

        return QuickIntent(
            category=best_category,
            confidence=best_confidence,
            requires_llm=requires_llm,
            estimated_complexity=complexity,
            detection_time=detection_time
        )

    def _match_patterns(self, text: str, patterns: List[str]) -> float:
        """Match text against patterns and return confidence"""
        matches = 0
        total_patterns = len(patterns)

        for pattern in patterns:
            if re.search(pattern, text):
                matches += 1

        if matches == 0:
            return 0.0

        # Base confidence from match ratio
        confidence = matches / total_patterns

        # Boost confidence for multiple matches
        if matches > 1:
            confidence = min(1.0, confidence * 1.2)

        return confidence

    def can_skip_llm(self, text: str) -> Tuple[bool, str]:
        """Check if text can be processed without LLM"""
        intent = self.detect(text)

        if not intent.requires_llm:
            return True, f"Simple {intent.category.value}"

        return False, "Requires LLM processing"

    def get_route_suggestion(self, text: str) -> Dict[str, any]:
        """Get routing suggestion for text"""
        intent = self.detect(text)

        return {
            "category": intent.category.value,
            "confidence": intent.confidence,
            "requires_llm": intent.requires_llm,
            "complexity": intent.estimated_complexity,
            "suggested_route": self._get_suggested_route(intent)
        }

    def _get_suggested_route(self, intent: QuickIntent) -> str:
        """Get suggested processing route"""
        if not intent.requires_llm:
            return "fast_response"

        if intent.category == IntentCategory.RESEARCH:
            return "research_tool"
        elif intent.category == IntentCategory.CODING:
            return "code_tool"
        elif intent.category == IntentCategory.FILE_OP:
            return "file_tool"
        else:
            return "llm_standard"

    def get_stats(self) -> Dict[str, any]:
        """Get detector statistics"""
        return {
            "total_detections": self.stats["total_detections"],
            "avg_detection_time": f"{self.stats['avg_detection_time']*1000:.2f}ms",
            "by_category": self.stats["by_category"]
        }


# Global instance
_quick_intent: Optional[QuickIntentDetector] = None


def get_quick_intent_detector() -> QuickIntentDetector:
    """Get or create global quick intent detector"""
    global _quick_intent
    if _quick_intent is None:
        _quick_intent = QuickIntentDetector()
    return _quick_intent
