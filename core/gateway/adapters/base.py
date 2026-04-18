from abc import ABC, abstractmethod
import inspect
from typing import Any, Callable, Dict, Optional
from ..message import UnifiedMessage
from ..response import UnifiedResponse

class BaseChannelAdapter(ABC):
    """Abstract base class for all channel adapters."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.on_message_callback: Optional[Callable] = None

    @abstractmethod
    async def connect(self):
        """Establish connection to the channel provider."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Gracefully close the connection."""
        pass

    @abstractmethod
    async def send_message(self, chat_id: str, response: UnifiedResponse):
        """Send a message to the specific chat/user in this channel."""
        pass

    def on_message(self, callback: Callable[[UnifiedMessage], Any]):
        """Register a callback for incoming messages."""
        if callback is None:
            self.on_message_callback = None
            return

        if inspect.iscoroutinefunction(callback):
            self.on_message_callback = callback
            return

        async def _async_callback(message: UnifiedMessage):
            result = callback(message)
            if inspect.isawaitable(result):
                return await result
            return result

        self.on_message_callback = _async_callback

    @abstractmethod
    def get_status(self) -> str:
        """Return the current connection status."""
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Return supported features (e.g., buttons, voice, images)."""
        pass
