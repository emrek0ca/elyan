from dataclasses import dataclass, field
from typing import List, Dict, Any

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

    def to_channel_envelope(self) -> "ChannelEnvelope":
        images: List[Dict[str, Any]] = []
        files: List[Dict[str, Any]] = []
        for item in list(self.attachments or []):
            if not isinstance(item, dict):
                continue
            atype = str(item.get("type") or "").strip().lower()
            mime = str(item.get("mime") or "").strip().lower()
            if atype == "image" or mime.startswith("image/"):
                images.append(dict(item))
            else:
                files.append(dict(item))
        return ChannelEnvelope(
            text=str(self.text or ""),
            images=images,
            files=files,
            metadata=dict(self.metadata or {}),
            fallback_text="",
            buttons=list(self.buttons or []),
            format=str(self.format or "plain"),
            channel_hints=dict(self.channel_hints or {}),
        )


@dataclass
class ChannelEnvelope:
    text: str
    images: List[Dict[str, Any]] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    fallback_text: str = ""
    buttons: List[Dict[str, Any]] = field(default_factory=list)
    format: str = "plain"
    channel_hints: Dict[str, Any] = field(default_factory=dict)

    def to_unified_response(self) -> UnifiedResponse:
        attachments = [*list(self.images or []), *list(self.files or [])]
        return UnifiedResponse(
            text=str(self.text or ""),
            attachments=attachments,
            buttons=list(self.buttons or []),
            format=str(self.format or "plain"),
            metadata=dict(self.metadata or {}),
            channel_hints=dict(self.channel_hints or {}),
        )
