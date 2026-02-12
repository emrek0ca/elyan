"""
Context-Aware Intelligence Engine
Learns user patterns, provides proactive suggestions, smart automation
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass
import json

from utils.logger import get_logger

logger = get_logger("context_intelligence")


@dataclass
class UserPattern:
    """Represents a learned user behavior pattern"""
    pattern_type: str  # time_based, frequency_based, sequence_based
    trigger: str  # What triggers this pattern
    actions: List[str]  # What actions follow
    confidence: float  # How confident we are (0-1)
    frequency: int  # How many times seen
    last_seen: float  # Unix timestamp
    time_of_day: Optional[str] = None  # morning, afternoon, evening, night
    day_of_week: Optional[str] = None  # monday, tuesday, etc.


class ContextIntelligence:
    """
    Context-Aware Intelligence Engine
    - Learns user behavior patterns
    - Provides proactive suggestions
    - Enables smart automation
    """

    def __init__(self):
        self.patterns: Dict[str, UserPattern] = {}
        self.action_history: List[Tuple[float, str, str]] = []  # (timestamp, action, context)
        self.time_based_stats: Dict[str, Counter] = defaultdict(Counter)  # time_slot -> action counts
        self.sequence_patterns: Dict[Tuple[str, str], int] = defaultdict(int)  # (action1, action2) -> count
        self.daily_suggestions_cache: Dict[str, List[str]] = {}

        logger.info("Context Intelligence Engine initialized")

    def get_time_slot(self, hour: Optional[int] = None) -> str:
        """Get current time slot"""
        if hour is None:
            hour = datetime.now().hour

        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        else:
            return "night"

    def get_day_type(self) -> str:
        """Get day type (weekday/weekend)"""
        day = datetime.now().weekday()
        return "weekend" if day >= 5 else "weekday"

    async def record_action(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: str = "default"
    ):
        """Record user action for pattern learning"""
        timestamp = time.time()
        ctx_str = json.dumps(context) if context else ""

        # Add to history (keep last 1000 actions)
        self.action_history.append((timestamp, action, ctx_str))
        if len(self.action_history) > 1000:
            self.action_history.pop(0)

        # Update time-based stats
        hour = datetime.now().hour
        time_slot = self.get_time_slot(hour)
        self.time_based_stats[time_slot][action] += 1

        # Update sequence patterns (what follows what)
        if len(self.action_history) >= 2:
            prev_action = self.action_history[-2][1]
            self.sequence_patterns[(prev_action, action)] += 1

        # Learn patterns periodically
        if len(self.action_history) % 10 == 0:
            await self._learn_patterns()

    async def _learn_patterns(self):
        """Analyze action history and learn patterns"""
        # Time-based patterns
        for time_slot, action_counts in self.time_based_stats.items():
            most_common = action_counts.most_common(3)
            for action, count in most_common:
                if count >= 3:  # Seen at least 3 times
                    pattern_key = f"time_{time_slot}_{action}"
                    confidence = min(count / 10.0, 1.0)  # Max confidence at 10 occurrences

                    self.patterns[pattern_key] = UserPattern(
                        pattern_type="time_based",
                        trigger=f"time_is_{time_slot}",
                        actions=[action],
                        confidence=confidence,
                        frequency=count,
                        last_seen=time.time(),
                        time_of_day=time_slot
                    )

        # Sequence patterns
        for (action1, action2), count in self.sequence_patterns.items():
            if count >= 2:  # Seen at least 2 times
                pattern_key = f"seq_{action1}_{action2}"
                confidence = min(count / 5.0, 1.0)

                self.patterns[pattern_key] = UserPattern(
                    pattern_type="sequence_based",
                    trigger=action1,
                    actions=[action2],
                    confidence=confidence,
                    frequency=count,
                    last_seen=time.time()
                )

    async def get_proactive_suggestions(
        self,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get proactive suggestions based on context and learned patterns
        Returns list of suggestions with reasoning
        """
        suggestions = []
        current_time = datetime.now()
        time_slot = self.get_time_slot(current_time.hour)
        day_type = self.get_day_type()

        # Check cache (suggestions valid for 1 hour)
        cache_key = f"{time_slot}_{day_type}"
        if cache_key in self.daily_suggestions_cache:
            cached_time, cached_suggestions = self.daily_suggestions_cache[cache_key]
            if time.time() - cached_time < 3600:
                return cached_suggestions[:limit]

        # Time-based suggestions
        for pattern_key, pattern in self.patterns.items():
            if pattern.pattern_type == "time_based" and pattern.time_of_day == time_slot:
                if pattern.confidence > 0.3:
                    suggestions.append({
                        "action": pattern.actions[0],
                        "reason": f"Genellikle {time_slot} saatlerinde yapıyorsunuz",
                        "confidence": pattern.confidence,
                        "type": "time_based",
                        "priority": pattern.confidence * pattern.frequency
                    })

        # Recent action-based suggestions
        if len(self.action_history) > 0:
            last_action = self.action_history[-1][1]
            for pattern_key, pattern in self.patterns.items():
                if pattern.pattern_type == "sequence_based" and pattern.trigger == last_action:
                    if pattern.confidence > 0.4:
                        suggestions.append({
                            "action": pattern.actions[0],
                            "reason": f"'{last_action}' sonrasında genellikle bunu yapıyorsunuz",
                            "confidence": pattern.confidence,
                            "type": "sequence",
                            "priority": pattern.confidence * 2  # Sequence patterns are more relevant
                        })

        # Sort by priority and return top N
        suggestions.sort(key=lambda x: x["priority"], reverse=True)
        result = suggestions[:limit]

        # Cache results
        self.daily_suggestions_cache[cache_key] = (time.time(), result)

        return result

    async def should_automate(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Determine if an action should be automated
        Returns (should_automate, reason)
        """
        # Check if there's a strong time-based pattern
        time_slot = self.get_time_slot()
        pattern_key = f"time_{time_slot}_{action}"

        if pattern_key in self.patterns:
            pattern = self.patterns[pattern_key]
            if pattern.confidence > 0.7 and pattern.frequency > 5:
                return True, f"Her {time_slot} saatlerinde yapılıyor (güven: {pattern.confidence:.0%})"

        # Check for strong daily patterns
        # Count occurrences in last 7 days at same time
        now = time.time()
        week_ago = now - (7 * 24 * 3600)
        same_time_actions = [
            a for t, a, _ in self.action_history
            if t > week_ago and a == action and self.get_time_slot(datetime.fromtimestamp(t).hour) == time_slot
        ]

        if len(same_time_actions) >= 5:  # 5+ times in same time slot over last week
            return True, f"Son 7 günde {len(same_time_actions)} kez aynı saatte yapıldı"

        return False, ""

    def get_context_summary(self) -> Dict[str, Any]:
        """Get summary of learned context and patterns"""
        return {
            "total_patterns": len(self.patterns),
            "time_based_patterns": sum(1 for p in self.patterns.values() if p.pattern_type == "time_based"),
            "sequence_patterns": sum(1 for p in self.patterns.values() if p.pattern_type == "sequence_based"),
            "total_actions_recorded": len(self.action_history),
            "high_confidence_patterns": sum(1 for p in self.patterns.values() if p.confidence > 0.7),
            "most_common_time_slot": max(self.time_based_stats.items(), key=lambda x: sum(x[1].values()))[0] if self.time_based_stats else None,
        }

    async def get_smart_insights(self) -> List[str]:
        """Generate smart insights about user behavior"""
        insights = []

        # Most productive time
        if self.time_based_stats:
            max_time_slot = max(self.time_based_stats.items(), key=lambda x: sum(x[1].values()))
            insights.append(f"En aktif olduğunuz zaman: {max_time_slot[0]}")

        # Most common action
        all_actions = Counter([a for _, a, _ in self.action_history])
        if all_actions:
            most_common = all_actions.most_common(1)[0]
            insights.append(f"En sık kullanılan komut: {most_common[0]} ({most_common[1]} kez)")

        # Automation opportunities
        automation_candidates = []
        for pattern_key, pattern in self.patterns.items():
            if pattern.confidence > 0.7 and pattern.frequency > 5:
                automation_candidates.append(pattern)

        if automation_candidates:
            insights.append(f"{len(automation_candidates)} işlem otomatikleştirilebilir")

        return insights


# Global instance
_context_intelligence: Optional[ContextIntelligence] = None


def get_context_intelligence() -> ContextIntelligence:
    """Get or create global context intelligence instance"""
    global _context_intelligence
    if _context_intelligence is None:
        _context_intelligence = ContextIntelligence()
    return _context_intelligence
