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
        self._sockets_by_chat_id: dict[str, Set[web.WebSocketResponse]] = {}
        self._socket_chat_ids: dict[web.WebSocketResponse, str] = {}
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
        auth_context = request.get("elyan_auth") if hasattr(request, "get") else None
        if not isinstance(auth_context, dict) or not str(auth_context.get("user_id") or "").strip():
            return web.json_response({"ok": False, "error": "user session required"}, status=403)
        session_id = str(auth_context.get("session_id") or "").strip()
        user_id = str(auth_context.get("user_id") or "").strip()
        chat_id = session_id or user_id
        user_name = str(auth_context.get("display_name") or auth_context.get("user_name") or "Guest").strip() or "Guest"

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        self._socket_chat_ids[ws] = chat_id
        self._sockets_by_chat_id.setdefault(chat_id, set()).add(ws)
        
        logger.info("New WebChat connection established.")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    unified_msg = UnifiedMessage(
                        id="ws_" + str(id(ws)),
                        channel_type="webchat",
                        channel_id=chat_id,
                        user_id=user_id,
                        user_name=user_name,
                        text=data.get("text", ""),
                        metadata={
                            "session_id": session_id,
                            "workspace_id": str(auth_context.get("workspace_id") or "").strip(),
                            "source": "webchat",
                        },
                    )
                    
                    if self.on_message_callback:
                        await self.on_message_callback(unified_msg)
                
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WS connection closed with exception {ws.exception()}")
        finally:
            self.sockets.discard(ws)
            resolved_chat_id = self._socket_chat_ids.pop(ws, "")
            if resolved_chat_id:
                group = self._sockets_by_chat_id.get(resolved_chat_id)
                if group is not None:
                    group.discard(ws)
                    if not group:
                        self._sockets_by_chat_id.pop(resolved_chat_id, None)
            
        return ws

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        # Deliver only to sockets that belong to the same authenticated chat/session.
        payload = json.dumps({
            "type": "response",
            "text": response.text,
            "format": response.format
        })

        target_chat_id = str(chat_id or "").strip()
        for ws in list(self._sockets_by_chat_id.get(target_chat_id, set())):
            await ws.send_str(payload)

    def get_status(self) -> str:
        # Must return "connected" so the supervisor doesn't keep retrying
        if self._is_running:
            return "connected"
        return "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {"html": True, "images": True, "streaming": True}
