from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time

@dataclass
class UnifiedMessage:
    """Agnostic message format for all channels."""
    id: str
    channel_type: str  # telegram, discord, whatsapp, web, etc.
    channel_id: str
    user_id: str
    user_name: str
    text: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    reply_to: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id,
            "channel_type": self.channel_type,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "text": self.text,
            "attachments": self.attachments,
            "reply_to": self.reply_to,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }
