"""
Conversational Flow Manager
Analyzes user messages for intent, sentiment, and conversation pattern.
"""

from __future__ import annotations

import re
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class FlowAnalysis:
    """Result of conversation flow analysis."""
    intent: str  # "question", "command", "statement", "clarification", "feedback"
    confidence: float  # 0.0-1.0
    sentiment: str  # "positive", "neutral", "negative"
    is_follow_up: bool
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ConversationFlowManager:
    """
    Analyzes conversation flow to understand user intent without ML overhead.
    Uses pattern matching and simple heuristics.
    """

    # Intent patterns
    QUESTION_PATTERNS = [
        r"^\s*(?:ne|nedir|nasıl|nerede|ne zaman|hangi|kim|kaç|var mı\?)",
        r"\?$",
        r"^(what|how|why|when|where|who|which|can|could|would|should)\b",
    ]

    COMMAND_PATTERNS = [
        r"(yap|kapat|aç|sil|taşı|oluştur|düzenle|ekle|kaldır|başla|durdur)",
        r"^(do|make|create|delete|move|open|close|start|stop|edit|run)",
    ]

    FEEDBACK_PATTERNS = [
        r"^(harika|mükemmel|kötü|berbat|iyi|fena|bok gibi|çok iyi)",
        r"^(good|bad|great|terrible|awesome|awful)",
        r"(thanks|thank you|teşekkür|eyvallah)",
    ]

    STATEMENT_PATTERNS = [
        r"^(ben|ben şu anda|bana|söyle|düşün|kontrol et|incele)",
        r"^(i|i'm|i am|i think|i want)",
    ]

    def __init__(self):
        self.conversation_history: List[Dict[str, Any]] = []

    def analyze(
        self, user_message: str, session_data: Dict[str, Any]
    ) -> FlowAnalysis:
        """
        Analyze conversation flow.

        Returns FlowAnalysis with intent, confidence, sentiment.
        """
        message_lower = user_message.lower().strip()

        # Determine intent
        intent = self._detect_intent(message_lower)
        confidence = self._confidence_for_intent(message_lower, intent)
        sentiment = self._analyze_sentiment(message_lower)
        is_follow_up = self._is_follow_up(
            user_message, session_data.get("messages", [])
        )

        return FlowAnalysis(
            intent=intent,
            confidence=confidence,
            sentiment=sentiment,
            is_follow_up=is_follow_up,
            metadata={
                "word_count": len(message_lower.split()),
                "has_punctuation": "?" in message_lower or "!" in message_lower,
            },
        )

    def _detect_intent(self, message: str) -> str:
        """Detect primary intent."""
        # Questions
        for pattern in self.QUESTION_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "question"

        # Commands
        for pattern in self.COMMAND_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "command"

        # Feedback
        for pattern in self.FEEDBACK_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "feedback"

        # Statements
        for pattern in self.STATEMENT_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "statement"

        return "clarification"  # Default

    def _confidence_for_intent(self, message: str, intent: str) -> float:
        """Estimate confidence in detected intent."""
        # Explicit markers increase confidence
        if "?" in message:
            return 0.95 if intent == "question" else 0.7
        if any(message.lower().startswith(w) for w in ["do", "make", "create", "yap", "kapat", "aç", "bunu"]):
            return 0.9 if intent == "command" else 0.6

        # Short messages are less confident
        if len(message.split()) < 3:
            return 0.65

        return 0.75

    def _analyze_sentiment(self, message: str) -> str:
        """Determine sentiment (positive, neutral, negative)."""
        positive_words = [
            "harika",
            "mükemmel",
            "iyi",
            "çok iyi",
            "güzel",
            "amazing",
            "great",
            "good",
            "excellent",
            "teşekkür",
            "thanks",
        ]
        negative_words = [
            "kötü",
            "berbat",
            "fena",
            "bok gibi",
            "bad",
            "terrible",
            "awful",
            "broken",
        ]

        word_list = message.split()
        pos_count = sum(1 for w in word_list if w in positive_words)
        neg_count = sum(1 for w in word_list if w in negative_words)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        else:
            return "neutral"

    def _is_follow_up(self, message: str, history: List[Dict[str, str]]) -> bool:
        """Detect if message is follow-up to previous message."""
        if not history:
            return False

        # Follow-up indicators
        follow_up_words = [
            "ve",
            "also",
            "ayrıca",
            "furthermore",
            "additionally",
            "bunun yanında",
            "o zaman",
            "then",
            "peki",
        ]
        message_lower = message.lower()

        for word in follow_up_words:
            if message_lower.startswith(word):
                return True

        # No explicit marker = not follow-up
        return False

    def record_turn(self, user_message: str, assistant_response: str) -> None:
        """Record conversation turn."""
        self.conversation_history.append(
            {"user": user_message, "assistant": assistant_response}
        )


__all__ = ["ConversationFlowManager", "FlowAnalysis"]
