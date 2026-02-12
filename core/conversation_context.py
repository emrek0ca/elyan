"""
Context Manager for Conversation

Extracts relevant context from conversation history and resolves references.
"""

from typing import Dict, List, Optional
from datetime import datetime
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
            "last_url": None,
            "last_file": None,
            "last_app": None
        }
        
        for msg in reversed(history):
            if msg["role"] == "assistant":
                content = msg["content"]
                
                # Extract URLs
                if not context["last_url"] and "http" in content:
                    urls = re.findall(r'https?://[^\s<>"]+', content)
                    if urls:
                        context["last_url"] = urls[0]
                
                # Extract files
                if not context["last_file"]:
                    paths = re.findall(r'/[\w/.-]+\.\w+', content)
                    if paths:
                        context["last_file"] = paths[0]
        
        return context
    
    def resolve_references(self, message: str, context: Dict) -> str:
        """Resolve pronouns using context"""
        message_lower = message.lower()
        
        # Check if needs resolution
        if not any(word in message_lower for word in ["onu", "bunu", "şimdi", "oradan"]):
            return message
        
        resolved = message
        
        # URL references
        if context.get("last_url"):
            if any(word in message_lower for word in ["onu aç", "oraya git"]):
                resolved = f"{context['last_url']} aç"
        
        logger.info(f"Resolved: {message} → {resolved}")
        return resolved
    
    def build_context_prompt(self, context: Dict) -> str:
        """Build context string for prompt"""
        if not context:
            return ""
        
        parts = []
        if context.get("last_url"):
            parts.append(f"Last URL: {context['last_url']}")
        if context.get("last_file"):
            parts.append(f"Last file: {context['last_file']}")
        
        return "\n".join(parts) if parts else ""


# Global singleton
_context_mgr = None


def get_conversation_context_manager():
    global _context_mgr
    if _context_mgr is None:
        _context_mgr = ConversationContextManager()
    return _context_mgr
