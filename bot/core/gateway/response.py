from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class UnifiedResponse:
    """Agnostic response format to be sent back to channels."""
    text: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    buttons: List[Dict[str, Any]] = field(default_factory=list)
    format: str = "markdown" # markdown, html, plain
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Hints for specific channel rendering
    channel_hints: Dict[str, Any] = field(default_factory=dict)
