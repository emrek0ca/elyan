import asyncio
import json
from aiohttp import web
from typing import Dict, Any, Set
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("webchat_adapter")

class WebChatAdapter(BaseChannelAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.sockets: Set[web.WebSocketResponse] = set()
        self._is_running = False

    async def connect(self):
        # The actual HTTP server setup is in gateway/server.py
        # This adapter just manages the socket state
        if self._is_running:
            return  # already connected — supervisor should not re-init
        self._is_running = True
        logger.info("WebChat adapter initialized.")

    async def disconnect(self):
        self._is_running = False
        for ws in list(self.sockets):
            await ws.close()
        self.sockets.clear()

    async def handle_ws(self, request):
        """HTTP Endpoint to be registered in server.py"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        
        logger.info("New WebChat connection established.")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    unified_msg = UnifiedMessage(
                        id="ws_" + str(id(ws)),
                        channel_type="webchat",
                        channel_id="browser",
                        user_id=data.get("user_id", "guest"),
                        user_name=data.get("user_name", "Guest"),
                        text=data.get("text", "")
                    )
                    
                    if self.on_message_callback:
                        await self.on_message_callback(unified_msg)
                
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WS connection closed with exception {ws.exception()}")
        finally:
            self.sockets.remove(ws)
            
        return ws

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        # Broadcast to all connected web clients
        # In a multi-user system, we would filter by chat_id
        payload = json.dumps({
            "type": "response",
            "text": response.text,
            "format": response.format
        })
        
        for ws in self.sockets:
            await ws.send_str(payload)

    def get_status(self) -> str:
        # Must return "connected" so the supervisor doesn't keep retrying
        if self._is_running:
            return "connected"
        return "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {"html": True, "images": True, "streaming": True}
