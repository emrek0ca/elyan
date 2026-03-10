from __future__ import annotations

from typing import Awaitable, Callable, Optional

from core.gateway.response import UnifiedResponse


class ChannelDeliveryBridge:
    def __init__(self):
        self._sender: Optional[Callable[[str, str, UnifiedResponse], Awaitable[None]]] = None

    def register_sender(self, sender: Callable[[str, str, UnifiedResponse], Awaitable[None]]) -> None:
        self._sender = sender

    async def deliver(self, channel_type: str, channel_id: str, response: UnifiedResponse) -> bool:
        if not callable(self._sender):
            return False
        if not str(channel_type or "").strip() or not str(channel_id or "").strip():
            return False
        await self._sender(str(channel_type), str(channel_id), response)
        return True


channel_delivery_bridge = ChannelDeliveryBridge()


__all__ = ["ChannelDeliveryBridge", "channel_delivery_bridge"]
