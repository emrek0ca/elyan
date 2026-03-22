"""
Context Manager for Conversation

Extracts relevant context from conversation history and resolves references.
"""

from typing import Dict, List, Optional
import re
from utils.logger import get_logger

logger = get_logger("conversation_context")


class ConversationContextManager:
    """Manages conversation context and reference resolution"""
    
    def __init__(self):
        self.user_contexts: Dict[int, Dict] = {}
    
    def extract_context(self, history: List[Dict]) -> Dict:
        """Extract context from conversation history"""
        if not history:
            return {}
        
        context = {
            "recent_topics": [],
            "last_task": None,
            "last_topic": None,
            "last_url": None,
            "last_file": None,
            "last_app": None,
        }

        for msg in reversed(history):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            content = str(msg.get("content") or msg.get("text") or msg.get("user_message") or msg.get("bot_response") or "").strip()
            if not content:
                continue

            if role in {"user", "assistant"} and content not in context["recent_topics"] and len(context["recent_topics"]) < 5:
                context["recent_topics"].append(content)

            if role == "user" and not context["last_topic"]:
                context["last_topic"] = content
            if role == "user" and not context["last_task"] and len(content.split()) >= 2:
                context["last_task"] = content

            lowered = content.lower()
            if not context["last_app"]:
                app_candidates = re.findall(
                    r'\b(chrome|safari|edge|firefox|brave|telegram|whatsapp|gmail|calendar|drive|docs|sheets|slides|excel|word|powerpoint|outlook|notion|slack|discord|x|instagram)\b',
                    lowered,
                )
                if app_candidates:
                    context["last_app"] = app_candidates[0]

            if not context["last_url"] and "http" in lowered:
                urls = re.findall(r'https?://[^\s<>"]+', content)
                if urls:
                    context["last_url"] = urls[0]

            if not context["last_file"]:
                paths = re.findall(r'(?:~?/[^ \n\t"\'<>]+\.\w+|[A-Za-z]:\\[^ \n\t"\'<>]+\.\w+)', content)
                if paths:
                    context["last_file"] = paths[0]
        
        return context
    
    def resolve_references(self, message: str, context: Dict) -> str:
        """Resolve pronouns using context"""
        message_lower = message.lower()
        ctx = dict(context or {})
        
        # Check if needs resolution
        if not any(word in message_lower for word in ["onu", "bunu", "şimdi", "oradan", "aynı", "devam", "hangi alanlarda", "mesela", "örnek"]):
            return message
        
        resolved = message
        resolved_changed = False

        # URL references
        if ctx.get("last_url") and any(word in message_lower for word in ["onu aç", "oraya git"]):
            resolved = f"{ctx['last_url']} aç"
            resolved_changed = True
        elif ctx.get("last_file") and any(word in message_lower for word in ["onu aç", "bunu aç", "şunu aç", "onu göster", "bunu göster"]):
            resolved = f"{ctx['last_file']} aç"
            resolved_changed = True
        elif ctx.get("last_app") and any(word in message_lower for word in ["onu aç", "oraya geç", "aç onu", "uygulamayı aç"]):
            resolved = f"{ctx['last_app']} aç"
            resolved_changed = True

        if ctx.get("last_topic") and not resolved_changed and any(word in message_lower for word in ["hangi alanlarda", "mesela", "örnek", "devam", "aynı"]):
            resolved = f"{ctx['last_topic']} {message}".strip()
        
        logger.info(f"Resolved: {message} → {resolved}")
        return resolved
    
    def build_context_prompt(self, context: Dict) -> str:
        """Build context string for prompt"""
        if not context:
            return ""
        
        parts = []
        if context.get("last_task"):
            parts.append(f"Last task: {context['last_task']}")
        if context.get("last_topic"):
            parts.append(f"Last topic: {context['last_topic']}")
        if context.get("last_url"):
            parts.append(f"Last URL: {context['last_url']}")
        if context.get("last_file"):
            parts.append(f"Last file: {context['last_file']}")
        if context.get("last_app"):
            parts.append(f"Last app: {context['last_app']}")
        recent_topics = list(context.get("recent_topics") or [])
        if recent_topics:
            parts.append("Recent topics: " + " | ".join(str(item) for item in recent_topics[:3] if item))
        
        return "\n".join(parts) if parts else ""


# Global singleton
_context_mgr = None


def get_conversation_context_manager():
    global _context_mgr
    if _context_mgr is None:
        _context_mgr = ConversationContextManager()
    return _context_mgr
