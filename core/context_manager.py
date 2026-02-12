"""
Context Manager for Intelligent Prompt Construction

Manages which context to include in LLM prompts based on:
- Recent conversation history
- User preferences
- Current system state
- Relevant past tasks
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from .memory import get_memory
from utils.logger import get_logger

logger = get_logger("context")


class ContextManager:
    """
    Manages context for LLM interactions
    
    Responsible for:
    - Selecting relevant conversation history
    - Including user preferences
    - Managing context window size
    - Prioritizing important information
    """
    
    def __init__(self, max_context_tokens: int = 4000):
        self.memory = get_memory()
        self.max_context_tokens = max_context_tokens
        # Lazy load LLM for summarization
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from .llm_client import LLMClient
            self._llm = LLMClient()
        return self._llm
    
    async def build_context(self, user_id: int, current_message: str, 
                     include_history: bool = True,
                     include_preferences: bool = True,
                     include_recent_tasks: bool = False) -> Dict[str, Any]:
        """
        Build comprehensive context for LLM prompt (v21.0 - Async & Sliding Window)
        """
        context = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "current_message": current_message
        }
        
        # Add conversation history with Sliding Window
        if include_history:
            history_data = await self._get_relevant_history_sliding_window(user_id, current_message)
            context["conversation_history"] = history_data["recent"]
            if history_data.get("summary"):
                context["historical_summary"] = history_data["summary"]
        
        # Add user preferences
        if include_preferences:
            context["user_preferences"] = self._get_user_preferences(user_id)
        
        # Add recent task outcomes
        if include_recent_tasks:
            context["recent_tasks"] = self._get_recent_tasks(user_id)
        
        # Add system state
        context["system_state"] = self._get_system_state()
        
        return context
    
    async def _get_relevant_history_sliding_window(self, user_id: int, current_message: str, 
                                                 window_size: int = 5) -> Dict[str, Any]:
        """
        Get sliding window history: recent N messages + summary of older ones
        """
        # 1. Get total recent history (say last 15)
        all_recent = self.memory.get_recent_conversations(user_id, limit=15)
        
        if not all_recent:
            return {"recent": [], "summary": None}
            
        # Recent window (keep last 5)
        recent = all_recent[:window_size]
        # Reverse to keep chronological order for LLM
        recent.reverse()
        
        # 2. If there are older messages, summarize them
        summary = None
        if len(all_recent) > window_size:
            older = all_recent[window_size:]
            older.reverse() # Chronological
            summary = await self.llm.summarize_context(older)
            
        return {"recent": recent, "summary": summary}

    def _get_relevant_history(self, user_id: int, current_message: str, 
                               max_messages: int = 5) -> List[Dict]:
        """Legacy sync method (kept for backward compatibility if needed)"""
        return self.memory.get_recent_conversations(user_id, limit=max_messages)
    
    def _get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Get user preferences that might be relevant"""
        prefs = self.memory.get_all_preferences(user_id)
        
        # Filter to most relevant preferences
        relevant_prefs = {}
        important_keys = [
            "preferred_language",
            "default_directory",
            "favorite_apps",
            "common_tasks",
            "notification_preferences"
        ]
        
        for key in important_keys:
            if key in prefs:
                relevant_prefs[key] = prefs[key]
        
        return relevant_prefs
    
    def _get_recent_tasks(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Get recent task outcomes for context"""
        tasks = self.memory.get_task_history(user_id, limit=limit)
        
        # Simplify task data for context
        simplified = []
        for task in tasks:
            simplified.append({
                "goal": task.get("goal", ""),
                "success": task.get("success", False),
                "timestamp": task.get("timestamp", "")
            })
        
        return simplified
    
    def _get_system_state(self) -> Dict[str, Any]:
        """Get current system state information"""
        return {
            "platform": "macOS",
            "timestamp": datetime.now().isoformat(),
            "memory_stats": self.memory.get_stats()
        }
    
    def _extract_keywords(self, text: str, max_keywords: int = 5) -> List[str]:
        """
        Extract important keywords from text
        
        Simple implementation - can be enhanced with NLP
        """
        # Remove common words
        stop_words = {
            "bir", "bu", "şu", "o", "ve", "veya", "ile", "için", "mi", "mı", "mu", "mü",
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "is", "are"
        }
        
        # Split and clean
        words = text.lower().split()
        keywords = []
        
        for word in words:
            # Remove punctuation
            word = ''.join(c for c in word if c.isalnum())
            # Filter
            if len(word) > 3 and word not in stop_words:
                keywords.append(word)
        
        # Return unique keywords
        return list(dict.fromkeys(keywords))[:max_keywords]
    
    def format_context_for_prompt(self, context: Dict[str, Any]) -> str:
        """
        Format context dictionary into a string for LLM prompt
        """
        parts = []
        
        # 1. Add historical summary (Sliding Window)
        if "historical_summary" in context and context["historical_summary"]:
            parts.append("## Conversation Summary (Older History)")
            parts.append(context["historical_summary"])
            parts.append("")

        # 2. Add recent conversation history
        if "conversation_history" in context and context["conversation_history"]:
            parts.append("## Recent Conversation History")
            for conv in context["conversation_history"]:
                user_msg = conv.get("user_message", "")[:200]
                action = conv.get("action", "unknown")
                parts.append(f"- User: {user_msg} → Action: {action}")
        
        # 3. Add preferences
        if "user_preferences" in context and context["user_preferences"]:
            parts.append("\n## User Preferences")
            for key, value in context["user_preferences"].items():
                parts.append(f"- {key}: {value}")
        
        # 4. Add recent tasks
        if "recent_tasks" in context and context["recent_tasks"]:
            parts.append("\n## Recent Tasks")
            for task in context["recent_tasks"][:3]:
                status = "✓" if task.get("success") else "✗"
                parts.append(f"- {status} {task.get('goal', '')[:80]}")
        
        return "\n".join(parts)
    
    def estimate_context_size(self, context: Dict[str, Any]) -> int:
        """
        Estimate context size in tokens (rough approximation)
        
        Rule of thumb: 1 token ≈ 4 characters
        """
        context_str = self.format_context_for_prompt(context)
        return len(context_str) // 4
    
    def learn_from_interaction(self, user_id: int, user_message: str, 
                               bot_response: Dict[str, Any]):
        """
        Learn user preferences from successful interactions
        
        Automatically extracts and stores patterns
        """
        # Learn language preference
        if self._is_turkish(user_message):
            self.memory.store_preference(user_id, "preferred_language", "tr", confidence=0.9)
        else:
            self.memory.store_preference(user_id, "preferred_language", "en", confidence=0.9)
        
        # Learn common actions
        action = bot_response.get("action")
        if action and bot_response.get("success", True):
            # Increment action count
            common_actions = self.memory.get_preference(user_id, "common_actions", default={})
            if not isinstance(common_actions, dict):
                common_actions = {}
            
            common_actions[action] = common_actions.get(action, 0) + 1
            self.memory.store_preference(user_id, "common_actions", 
                                        json.dumps(common_actions), confidence=0.8)
        
        # Learn directory preferences
        if "path" in bot_response or "directory" in bot_response:
            path = bot_response.get("path") or bot_response.get("directory", "")
            if path and "/" in path:
                # Extract base directory
                base_dir = "/".join(path.split("/")[:-1])
                self.memory.store_preference(user_id, "frequently_used_directory", 
                                            base_dir, confidence=0.7)
    
    def _is_turkish(self, text: str) -> bool:
        """Simple Turkish detection"""
        turkish_chars = set('çğıöşüÇĞİÖŞÜ')
        return any(char in text for char in turkish_chars)


# Global context manager instance
_context_manager = None


def get_context_manager() -> ContextManager:
    """Get or create the global context manager"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
