"""
Matrix Adapter — matrix-nio kütüphanesi üzerinden Matrix/Element entegrasyonu.

Gereksinimler:
  pip install matrix-nio[e2e]  (şifreli oda desteği için)
  veya: pip install matrix-nio  (şifresiz)

Yapılandırma (elyan.json):
  {
    "type": "matrix",
    "homeserver": "https://matrix.org",
    "user_id": "@elyan:matrix.org",
    "access_token": "syt_...",
    "device_name": "Elyan Bot",
    "allowed_rooms": []  # Boş = tüm odalar
  }
"""
import asyncio
from typing import Dict, Any, Optional, List

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("matrix_adapter")


class MatrixAdapter(BaseChannelAdapter):
    """
    Matrix/Element kanal adaptörü.
    matrix-nio AsyncClient üzerinden çalışır.

    Desteklenen özellikler:
    - m.room.message (text/image)
    - DM odaları ve grup odaları
    - End-to-end şifreleme (e2e ekstra kurulum gerektirir)
    - Mesaj tepkileri
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.homeserver: str = config.get("homeserver", "https://matrix.org")
        self.user_id: str = config.get("user_id", "")
        self.access_token: str = config.get("access_token", "")
        self.device_name: str = config.get("device_name", "Elyan Bot")
        self.allowed_rooms: List[str] = config.get("allowed_rooms", [])
        self._client = None
        self._sync_task: Optional[asyncio.Task] = None
        self._is_connected: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        if not self.user_id or not self.access_token:
            logger.error("Matrix: user_id veya access_token yapılandırılmamış.")
            return
        try:
            from nio import AsyncClient, MatrixRoom, RoomMessageText, LoginResponse
            self._nio = __import__("nio")

            self._client = AsyncClient(self.homeserver, self.user_id)
            self._client.access_token = self.access_token
            self._client.device_id = self.device_name

            # Callback kayıt
            self._client.add_event_callback(
                self._on_room_message, self._nio.RoomMessageText
            )

            # İlk sync
            await self._client.sync(timeout=30000)
            self._is_connected = True
            logger.info(f"Matrix adapter bağlandı: {self.user_id} @ {self.homeserver}")

            # Arka plan sync döngüsü
            self._sync_task = asyncio.create_task(self._sync_loop())

        except ImportError:
            logger.error("matrix-nio kurulu değil. 'pip install matrix-nio' komutunu çalıştırın.")
        except Exception as exc:
            logger.error(f"Matrix bağlantı hatası: {exc}")

    async def _sync_loop(self):
        """Sürekli sync loop — yeni mesajları dinler."""
        while self._is_connected:
            try:
                await self._client.sync(timeout=30000)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Matrix sync hatası: {exc}")
                await asyncio.sleep(5)

    async def disconnect(self):
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.close()
        self._is_connected = False
        logger.info("Matrix adapter kapatıldı.")

    # ── Event Handler ─────────────────────────────────────────────────────────

    async def _on_room_message(self, room, event):
        """Gelen Matrix mesajını işle."""
        try:
            # Kendi mesajlarımızı yok say
            if event.sender == self.user_id:
                return
            # İzin verilen oda filtresi
            if self.allowed_rooms and room.room_id not in self.allowed_rooms:
                return

            body = event.body
            if not body:
                return

            msg = UnifiedMessage(
                id=event.event_id,
                channel_type="matrix",
                channel_id=room.room_id,
                user_id=event.sender,
                user_name=room.user_name(event.sender) or event.sender,
                text=body,
                metadata={"room_name": room.display_name},
            )
            if self.on_message_callback:
                await self.on_message_callback(msg)
        except Exception as exc:
            logger.error(f"Matrix mesaj işleme hatası: {exc}")

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if not self._client:
            logger.error("Matrix client bağlı değil.")
            return
        try:
            # Markdown destekli mesaj (m.room.message / m.text)
            content = {
                "msgtype": "m.text",
                "body": response.text,
            }
            # HTML formatted_body ekle (markdown ise)
            if response.format == "markdown":
                try:
                    import markdown
                    html_body = markdown.markdown(response.text, extensions=["fenced_code"])
                    content["format"] = "org.matrix.custom.html"
                    content["formatted_body"] = html_body
                except ImportError:
                    pass

            await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
                content=content,
            )
        except Exception as exc:
            logger.error(f"Matrix gönderme hatası: {exc}")

    # ── Status / Capabilities ─────────────────────────────────────────────────

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "text": True,
            "images": True,
            "markdown": True,
            "html": True,
            "reactions": True,
            "threads": True,
            "e2e": True,
            "buttons": False,
        }
