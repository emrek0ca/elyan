"""chat_widget.py — backward-compat shim (Sprint J)"""

from ui.clean_chat_widget import (
    CleanChatWidget as ChatWidget,
    CleanMessageBubble as MessageBubble,
    CleanTypingIndicator as TypingIndicator,
)

__all__ = ["ChatWidget", "MessageBubble", "TypingIndicator"]
