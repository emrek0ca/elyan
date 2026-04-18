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
from collections import deque
from typing import Dict, Any, List, Optional

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
        self._poll_failure_streak: int = 0
        self._recent_message_ids: deque[str] = deque(maxlen=512)
        self._seen_message_ids: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self):
        if not self.server_url or not self.password:
            logger.error("iMessage: server_url veya password yapılandırılmamış.")
            return
        try:
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = aiohttp.ClientSession()
            # Bağlantıyı doğrula
            ok = await self._ping()
            if not ok:
                logger.error("iMessage: BlueBubbles sunucusuna ulaşılamıyor.")
                await self._session.close()
                self._session = None
                return
            self._is_connected = True
            self._poll_failure_streak = 0
            logger.info(f"iMessage adapter bağlandı: {self.server_url}")
            # BlueBubbles Socket.IO kimlik doğrulaması query-string gerektiriyor.
            # Release build'de secret'ı URL'e koymak yerine bu yolu kapatıyoruz.
            if self._supports_secure_websocket():
                self._ws_task = asyncio.create_task(self._ws_loop())
            else:
                if not self._poll_task or self._poll_task.done():
                    self._poll_task = asyncio.create_task(self._poll_loop())
                logger.info("iMessage polling modu aktif: BlueBubbles REST API izleniyor.")
        except Exception as exc:
            logger.error(f"iMessage bağlantı hatası: {exc}")
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None

    async def disconnect(self):
        for task in (self._ws_task, self._poll_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ws_task = None
        self._poll_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session:
            await self._session.close()
            self._session = None
        self._is_connected = False
        self._poll_failure_streak = 0
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

    def _supports_secure_websocket(self) -> bool:
        return False

    async def _ws_loop(self):
        """BlueBubbles WebSocket üzerinden canlı mesaj dinleme."""
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/v1/socket.io/?EIO=4&transport=websocket"

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

    @staticmethod
    def _message_timestamp_ms(message: dict[str, Any]) -> int:
        for key in ("dateCreated", "timestamp", "createdAt", "dateCreatedEpoch"):
            raw = message.get(key)
            if raw is None:
                continue
            try:
                if isinstance(raw, str):
                    cleaned = raw.strip()
                    if not cleaned:
                        continue
                    value = int(float(cleaned))
                else:
                    value = int(float(raw))
            except Exception:
                continue
            if value < 1_000_000_000_000:
                value *= 1000
            return max(0, value)
        return 0

    @staticmethod
    def _message_identifier(message: dict[str, Any]) -> str:
        for key in ("guid", "id", "messageGuid", "chatGuid"):
            value = str(message.get(key) or "").strip()
            if value:
                return value
        return ""

    def _remember_message_id(self, message_id: str) -> bool:
        mid = str(message_id or "").strip()
        if not mid:
            return True
        if mid in self._seen_message_ids:
            return False
        if self._recent_message_ids.maxlen and len(self._recent_message_ids) >= self._recent_message_ids.maxlen:
            oldest = self._recent_message_ids.popleft()
            self._seen_message_ids.discard(oldest)
        self._recent_message_ids.append(mid)
        self._seen_message_ids.add(mid)
        return True

    async def _poll_loop(self):
        """BlueBubbles REST API üzerinden düzenli polling."""
        while self._is_connected:
            try:
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()

                url = f"{self.server_url}/api/v1/message"
                params = {
                    "password": self.password,
                    "limit": 10,
                    "offset": 0,
                    "sort": "DESC",
                    "after": self._last_poll_ts,
                }
                timeout = aiohttp.ClientTimeout(total=10)
                async with self._session.get(url, params=params, timeout=timeout) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"BlueBubbles polling HTTP {resp.status}: {body[:240]}")
                    data = await resp.json()

                items: list[dict[str, Any]] = []
                if isinstance(data, dict):
                    raw_items = data.get("data") or data.get("messages") or []
                    if isinstance(raw_items, list):
                        items = [item for item in raw_items if isinstance(item, dict)]

                if items:
                    for item in reversed(items):
                        timestamp = self._message_timestamp_ms(item)
                        if timestamp > self._last_poll_ts:
                            self._last_poll_ts = timestamp
                        identifier = self._message_identifier(item)
                        if identifier and not self._remember_message_id(identifier):
                            continue
                        await self._process_message(item)
                    self._poll_failure_streak = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._poll_failure_streak += 1
                logger.warning(f"iMessage poll error: {exc}")
                if self._poll_failure_streak >= 3:
                    logger.error("iMessage polling kesildi; adapter pasif moda alınıyor.")
                    self._is_connected = False
                    break
            try:
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break

        if self._session and not self._session.closed and not self._is_connected:
            await self._session.close()

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
            raise RuntimeError("iMessage session yok")
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
                    raise RuntimeError(f"iMessage HTTP {resp.status}: {body[:240]}")
        except Exception as exc:
            logger.error(f"iMessage send hatası: {exc}")
            raise

    async def send_reaction(self, chat_id: str, message_guid: str, reaction: str = "love"):
        """
        Tapback (tepki) gönder.
        reaction: love | like | dislike | laugh | emphasize | question
        """
        if not self._session:
            raise RuntimeError("iMessage session yok.")
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
                    body = await resp.text()
                    logger.error(f"iMessage tepki hatası {resp.status}: {body}")
                    raise RuntimeError(f"iMessage reaction HTTP {resp.status}: {body[:240]}")
        except Exception as exc:
            logger.error(f"iMessage tepki gönderme hatası: {exc}")
            raise

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
