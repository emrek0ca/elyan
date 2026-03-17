"""
Smart Context Manager - Multi-turn conversation memory and context
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import deque
import logging

logger = logging.getLogger(__name__)


class ConversationTurn:
    """Single turn in conversation"""

    def __init__(self, role: str, content: str, metadata: Dict = None):
        self.role = role  # "user" or "assistant"
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.now().isoformat()
        self.entities = []
        self.intent = None
        self.sentiment = None

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "entities": self.entities,
            "intent": self.intent,
            "sentiment": self.sentiment
        }


class SmartContextManager:
    """Manages multi-turn conversation context"""

    def __init__(self, max_turns: int = 10, max_tokens: int = 8000):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.turns: deque = deque(maxlen=max_turns)
        self.entities: Dict[str, List[str]] = {}
        self.intent_history: List[str] = []
        self.relationships: List[Dict] = []
        self.summary = None
        self.token_count = 0

    def add_turn(self, role: str, content: str, metadata: Dict = None) -> str:
        """Add conversation turn"""
        try:
            turn = ConversationTurn(role, content, metadata)

            # Extract entities and intent
            turn.entities = self._extract_entities(content)
            turn.intent = self._detect_intent(content)
            turn.sentiment = self._analyze_sentiment(content)

            # Update entity tracking
            self._update_entity_tracking(turn.entities)

            # Track intent evolution
            if turn.intent:
                self.intent_history.append(turn.intent)

            self.turns.append(turn)
            self.token_count += len(content.split())

            # Compress if needed
            if self.token_count > self.max_tokens:
                self._compress_context()

            return f"Turn added: {role} - {len(content)} chars"

        except Exception as e:
            logger.error(f"Failed to add turn: {e}")
            return f"Error: {e}"

    def _extract_entities(self, content: str) -> List[Dict]:
        """Extract named entities from content"""
        entities = []
        # Simplified entity extraction
        words = content.split()
        for i, word in enumerate(words):
            if word[0].isupper() and len(word) > 2:
                entities.append({
                    "text": word,
                    "type": "ENTITY",
                    "position": i
                })
        return entities

    def _detect_intent(self, content: str) -> Optional[str]:
        """Detect user intent"""
        content_lower = content.lower()
        intents = {
            "ask": ["how", "what", "why", "where", "when"],
            "request": ["can you", "please", "could you", "would you"],
            "inform": ["i think", "i believe", "it is"],
            "clarify": ["i mean", "in other words", "that is"],
            "agree": ["yes", "agree", "right", "correct"],
            "disagree": ["no", "disagree", "wrong", "incorrect"]
        }

        for intent, keywords in intents.items():
            if any(kw in content_lower for kw in keywords):
                return intent

        return None

    def _analyze_sentiment(self, content: str) -> str:
        """Analyze sentiment"""
        positive_words = ["good", "great", "excellent", "happy", "yes"]
        negative_words = ["bad", "terrible", "poor", "sad", "no"]

        pos_count = sum(1 for w in positive_words if w in content.lower())
        neg_count = sum(1 for w in negative_words if w in content.lower())

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        else:
            return "neutral"

    def _update_entity_tracking(self, entities: List[Dict]):
        """Track entities across conversation"""
        for entity in entities:
            entity_type = entity["type"]
            if entity_type not in self.entities:
                self.entities[entity_type] = []
            if entity["text"] not in self.entities[entity_type]:
                self.entities[entity_type].append(entity["text"])

    def get_context(self, limit: int = None) -> Dict:
        """Get current context"""
        limit = limit or self.max_turns
        recent_turns = list(self.turns)[-limit:]

        return {
            "turns": [t.to_dict() for t in recent_turns],
            "entity_count": len(self.entities),
            "entities": self.entities,
            "current_intent": self.intent_history[-1] if self.intent_history else None,
            "token_count": self.token_count,
            "turn_count": len(self.turns)
        }

    def summarize_context(self) -> str:
        """Summarize context"""
        try:
            if not self.turns:
                return "No context yet"

            summary_parts = []

            # Add recent intents
            if self.intent_history:
                recent_intents = self.intent_history[-3:]
                summary_parts.append(f"Recent intents: {', '.join(set(recent_intents))}")

            # Add key entities
            if self.entities:
                for ent_type, ents in self.entities.items():
                    summary_parts.append(f"{ent_type}: {', '.join(ents[:3])}")

            # Add conversation flow
            summary_parts.append(f"Conversation turns: {len(self.turns)}")

            return "; ".join(summary_parts)

        except Exception as e:
            logger.error(f"Failed to summarize: {e}")
            return "Error summarizing context"

    def identify_intent_evolution(self) -> Dict:
        """Identify how user intent is evolving"""
        try:
            if len(self.intent_history) < 2:
                return {"status": "Insufficient data"}

            # Count intent frequencies
            from collections import Counter
            intent_counts = Counter(self.intent_history)

            # Detect evolution
            evolution = {
                "total_intent_changes": len(set(self.intent_history)),
                "most_frequent_intent": intent_counts.most_common(1)[0] if intent_counts else None,
                "intent_progression": self.intent_history[-5:],
                "stability": 1.0 - (len(set(self.intent_history)) / len(self.intent_history))
            }

            return evolution

        except Exception as e:
            logger.error(f"Failed to identify evolution: {e}")
            return {"error": str(e)}

    def _compress_context(self):
        """Compress context when token limit reached"""
        try:
            if len(self.turns) > self.max_turns // 2:
                # Keep only summary + recent turns
                old_turns = list(self.turns)[:-3]
                new_turns = list(self.turns)[-3:]

                # Create summary of old turns
                summary_text = " ".join([t.content for t in old_turns])[:200]

                # Clear and rebuild
                self.turns.clear()
                summary_turn = ConversationTurn("system", f"[Summary: {summary_text}...]")
                self.turns.append(summary_turn)

                for turn in new_turns:
                    self.turns.append(turn)

                # Reduce token count
                self.token_count = sum(len(t.content.split()) for t in self.turns)

                logger.info("Context compressed")

        except Exception as e:
            logger.error(f"Failed to compress context: {e}")

    def suggest_next_action(self) -> str:
        """Suggest what user should do next"""
        try:
            if not self.turns:
                return "Start by describing your task"

            last_intent = self.intent_history[-1] if self.intent_history else None
            recent_content = self.turns[-1].content if self.turns else ""

            suggestions = {
                "ask": "Would you like more details or examples?",
                "request": "I can help with that. Do you need me to start now?",
                "inform": "Thank you for the context. What would you like me to do?",
                "clarify": "I understand now. Shall we proceed?",
                "agree": "Great! Let's move forward.",
                "disagree": "Let's explore other approaches."
            }

            return suggestions.get(last_intent, "What would you like to do next?")

        except Exception as e:
            logger.error(f"Failed to suggest action: {e}")
            return "What would you like to do next?"

    def get_memory_efficiency(self) -> Dict:
        """Check memory efficiency"""
        return {
            "turns_stored": len(self.turns),
            "max_turns": self.max_turns,
            "token_count": self.token_count,
            "max_tokens": self.max_tokens,
            "entities_tracked": len(self.entities),
            "memory_usage_percent": (self.token_count / self.max_tokens) * 100
        }

    def reset(self):
        """Reset context"""
        self.turns.clear()
        self.entities.clear()
        self.intent_history.clear()
        self.token_count = 0
        logger.info("Context reset")
