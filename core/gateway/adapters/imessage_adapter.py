"""
iMessage Adapter — BlueBubbles REST API üzerinden iMessage entegrasyonu.

BlueBubbles, macOS'ta çalışan ve iMessage'a HTTP/WebSocket erişim sağlayan
açık kaynaklı bir sunucu uygulamasıdır.

Gereksinimler:
  - macOS bilgisayarda BlueBubbles Server çalışıyor olmalı
    (https://github.com/BlueBubblesApp/bluebubbles-server)
  - REST API + WebSocket modunda açık

Yapılandırma (elyan.json):
  {
    "type": "imessage",
    "server_url": "http://192.168.1.10:1234",
    "password": "your_bb_password",
    "allowed_chats": [],     // Boş = tüm sohbetler
    "handle": "+905551234567"  // Bot'un iMessage handle'ı
  }
"""
import asyncio
import json
from typing import Dict, Any, List, Optional
from urllib.parse import quote

import aiohttp

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("imessage_adapter")


class IMessageAdapter(BaseChannelAdapter):
    """
    iMessage kanal adaptörü (BlueBubbles Server üzerinden).

    Mesaj alma: BlueBubbles WebSocket veya polling
    Mesaj gönderme: BlueBubbles REST API POST /api/v1/message/text

    Desteklenen özellikler:
    - 1-1 sohbet ve grup sohbetleri
    - Metin mesajları alma/gönderme
    - Tepkiler (tapback)
    - Okundu bilgisi
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.server_url: str = config.get("server_url", "http://localhost:1234").rstrip("/")
        self.password: str = config.get("password", "")
        self.allowed_chats: List[str] = config.get("allowed_chats", [])
        self.handle: str = config.get("handle", "")
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._is_connected: bool = False
        self._last_poll_ts: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self):
        if not self.server_url or not self.password:
            logger.error("iMessage: server_url veya password yapılandırılmamış.")
            return
        try:
            self._session = aiohttp.ClientSession()
            # Bağlantıyı doğrula
            ok = await self._ping()
            if not ok:
                logger.error("iMessage: BlueBubbles sunucusuna ulaşılamıyor.")
                return
            self._is_connected = True
            logger.info(f"iMessage adapter bağlandı: {self.server_url}")
            # WebSocket dinleyici başlat
            self._ws_task = asyncio.create_task(self._ws_loop())
        except Exception as exc:
            logger.error(f"iMessage bağlantı hatası: {exc}")

    async def disconnect(self):
        for task in (self._ws_task, self._poll_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
        self._is_connected = False
        logger.info("iMessage adapter kapatıldı.")

    # ── Ping ──────────────────────────────────────────────────────────────────

    async def _ping(self) -> bool:
        """BlueBubbles sunucu erişilebilirliğini kontrol et."""
        try:
            url = f"{self.server_url}/api/v1/ping"
            params = {"password": self.password}
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == 200
        except Exception:
            pass
        return False

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def _ws_loop(self):
        """BlueBubbles WebSocket üzerinden canlı mesaj dinleme."""
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/v1/socket.io/?password={quote(self.password)}&EIO=4&transport=websocket"

        while self._is_connected:
            try:
                async with self._session.ws_connect(ws_url) as ws:
                    self._ws = ws
                    logger.info("iMessage WebSocket bağlandı.")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                            break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"iMessage WebSocket hatası: {exc}, yeniden bağlanıyor...")
                await asyncio.sleep(5)

    async def _handle_ws_message(self, raw: str):
        """Socket.IO mesaj protokolünü parse et."""
        # Socket.IO prefix: "42[event,data]"
        if not raw.startswith("42"):
            return
        try:
            payload = json.loads(raw[2:])  # ["event", {data}]
            if not isinstance(payload, list) or len(payload) < 2:
                return
            event = payload[0]
            data = payload[1]
            if event == "new-message":
                await self._process_message(data)
        except (json.JSONDecodeError, IndexError):
            pass

    # ── Message Processing ────────────────────────────────────────────────────

    async def _process_message(self, data: dict):
        """Gelen iMessage mesajını UnifiedMessage'a dönüştür."""
        try:
            msg_obj = data.get("message", data)
            # Kendi gönderdiğimiz mesajları yok say
            if msg_obj.get("isFromMe", False):
                return
            # Sistem mesajları yok say
            if msg_obj.get("itemType", 0) != 0:
                return

            text = msg_obj.get("text", "").strip()
            if not text:
                return

            chat = msg_obj.get("chats", [{}])[0]
            chat_guid = chat.get("guid", "")

            # İzin verilen sohbet filtresi
            if self.allowed_chats and chat_guid not in self.allowed_chats:
                return

            handle_obj = msg_obj.get("handle") or {}
            sender = handle_obj.get("address", handle_obj.get("id", "unknown"))

            msg = UnifiedMessage(
                id=msg_obj.get("guid", ""),
                channel_type="imessage",
                channel_id=chat_guid,
                user_id=sender,
                user_name=sender,
                text=text,
                metadata={
                    "is_group": chat.get("isGroupChat", False),
                    "chat_display_name": chat.get("displayName", ""),
                    "service": msg_obj.get("service", "iMessage"),
                },
            )
            if self.on_message_callback:
                await self.on_message_callback(msg)
        except Exception as exc:
            logger.error(f"iMessage mesaj işleme hatası: {exc}")

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        """BlueBubbles REST API ile mesaj gönder."""
        if not self._session:
            logger.error("iMessage session yok.")
            return
        try:
            url = f"{self.server_url}/api/v1/message/text"
            payload = {
                "chatGuid": chat_id,
                "message": response.text,
                "method": "private-api",  # veya "apple-script"
                "subject": "",
                "effectId": None,
                "selectedMessageGuid": None,
                "partIndex": 0,
            }
            params = {"password": self.password}
            post_ctx = self._session.post(url, json=payload, params=params)
            if asyncio.iscoroutine(post_ctx):
                post_ctx = await post_ctx
            async with post_ctx as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(f"iMessage gönderim hatası {resp.status}: {body}")
        except Exception as exc:
            logger.error(f"iMessage send hatası: {exc}")

    async def send_reaction(self, chat_id: str, message_guid: str, reaction: str = "love"):
        """
        Tapback (tepki) gönder.
        reaction: love | like | dislike | laugh | emphasize | question
        """
        if not self._session:
            return
        reaction_map = {
            "love": 2000, "like": 2001, "dislike": 2002,
            "laugh": 2003, "emphasize": 2004, "question": 2005,
        }
        reaction_type = reaction_map.get(reaction, 2001)
        try:
            url = f"{self.server_url}/api/v1/message/react"
            payload = {
                "chatGuid": chat_id,
                "selectedMessageGuid": message_guid,
                "reactionType": reaction_type,
            }
            params = {"password": self.password}
            post_ctx = self._session.post(url, json=payload, params=params)
            if asyncio.iscoroutine(post_ctx):
                post_ctx = await post_ctx
            async with post_ctx as resp:
                if resp.status not in (200, 201):
                    logger.error(f"iMessage tepki hatası {resp.status}")
        except Exception as exc:
            logger.error(f"iMessage tepki gönderme hatası: {exc}")

    # ── Status / Capabilities ─────────────────────────────────────────────────

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "text": True,
            "images": True,
            "reactions": True,
            "read_receipts": True,
            "groups": True,
            "markdown": False,
            "buttons": False,
        }
