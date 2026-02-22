"""
core/genesis/adaptive_learning.py
─────────────────────────────────────────────────────────────────────────────
Adaptive Learning Module (Phase 29).
Tracks user interaction patterns over time to optimize Elyan's behavior.
- Learns which tools the user prefers
- Tracks peak activity hours
- Adjusts response verbosity based on user engagement
"""

import time
import json
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List
from utils.logger import get_logger

logger = get_logger("adaptive_learning")

@dataclass
class UserProfile:
    total_interactions: int = 0
    preferred_tools: Dict[str, int] = field(default_factory=lambda: Counter())
    activity_hours: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    avg_message_length: float = 0.0
    preferred_language: str = "tr"
    verbosity_preference: str = "detailed"  # minimal, normal, detailed
    last_interaction: float = field(default_factory=time.time)

class AdaptiveLearning:
    def __init__(self):
        self.profile_path = Path.home() / ".elyan" / "user_profile.json"
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = self._load_profile()
    
    def _load_profile(self) -> UserProfile:
        if self.profile_path.exists():
            try:
                data = json.loads(self.profile_path.read_text(encoding="utf-8"))
                profile = UserProfile()
                profile.total_interactions = data.get("total_interactions", 0)
                profile.preferred_tools = Counter(data.get("preferred_tools", {}))
                profile.activity_hours = defaultdict(int, data.get("activity_hours", {}))
                profile.avg_message_length = data.get("avg_message_length", 0.0)
                profile.preferred_language = data.get("preferred_language", "tr")
                profile.verbosity_preference = data.get("verbosity_preference", "detailed")
                return profile
            except:
                pass
        return UserProfile()
    
    def _save_profile(self):
        data = {
            "total_interactions": self.profile.total_interactions,
            "preferred_tools": dict(self.profile.preferred_tools),
            "activity_hours": dict(self.profile.activity_hours),
            "avg_message_length": self.profile.avg_message_length,
            "preferred_language": self.profile.preferred_language,
            "verbosity_preference": self.profile.verbosity_preference,
            "last_interaction": self.profile.last_interaction
        }
        self.profile_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def record_interaction(self, message: str, tool_used: str = None):
        """Called after every user interaction to update the learning model."""
        self.profile.total_interactions += 1
        self.profile.last_interaction = time.time()
        
        # Track activity hours
        current_hour = time.localtime().tm_hour
        self.profile.activity_hours[str(current_hour)] = \
            self.profile.activity_hours.get(str(current_hour), 0) + 1
        
        # Track tool usage
        if tool_used:
            self.profile.preferred_tools[tool_used] = \
                self.profile.preferred_tools.get(tool_used, 0) + 1
        
        # Rolling average message length
        n = self.profile.total_interactions
        self.profile.avg_message_length = (
            (self.profile.avg_message_length * (n - 1) + len(message)) / n
        )
        
        # Auto-detect verbosity preference
        if self.profile.avg_message_length < 20:
            self.profile.verbosity_preference = "minimal"
        elif self.profile.avg_message_length < 80:
            self.profile.verbosity_preference = "normal"
        else:
            self.profile.verbosity_preference = "detailed"
        
        self._save_profile()
        logger.debug(f"📊 Adaptive Learning Updated: {self.profile.total_interactions} interactions logged.")
    
    def get_peak_hours(self) -> List[int]:
        """Returns the user's top 3 most active hours."""
        sorted_hours = sorted(
            self.profile.activity_hours.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        return [int(h) for h, _ in sorted_hours[:3]]
    
    def get_top_tools(self, n: int = 5) -> List[str]:
        """Returns the user's most-used tools."""
        return [tool for tool, _ in self.profile.preferred_tools.most_common(n)]
    
    def should_be_proactive(self) -> bool:
        """Determines if Elyan should proactively suggest things based on user patterns."""
        peak = self.get_peak_hours()
        current = time.localtime().tm_hour
        return current in peak

# Global singleton
adaptive = AdaptiveLearning()
