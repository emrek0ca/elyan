"""
Signal Adapter — signald HTTP bridge üzerinden Signal entegrasyonu.

Gereksinimler:
  - signald daemon (https://signald.org) çalışıyor olmalı
  - signald HTTP proxy (signald-http-proxy) veya unix socket

Yapılandırma (elyan.json):
  {
    "type": "signal",
    "socket_path": "/var/run/signald/signald.sock",  # veya
    "http_url": "http://localhost:8080",              # HTTP proxy varsa
    "phone_number": "+905551234567"                  # Bot'un telefon numarası
  }
"""
import asyncio
import json
import os
import aiohttp
from typing import Dict, Any, Optional

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("signal_adapter")


class SignalAdapter(BaseChannelAdapter):
    """
    Signal kanal adaptörü.
    signald unix socket veya HTTP proxy üzerinden çalışır.

    Desteklenen özellikler:
    - Metin mesajları alma/gönderme
    - DM (1-1) ve grup mesajları
    - Dosya/resim gönderme (yol ile)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.phone_number: str = config.get("phone_number", "")
        self.http_url: str = config.get("http_url", "http://localhost:8080")
        self.socket_path: str = config.get("socket_path", "/var/run/signald/signald.sock")
        self._use_http: bool = bool(config.get("http_url"))
        self._session: Optional[aiohttp.ClientSession] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._is_connected: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        if not self.phone_number:
            logger.error("Signal: telefon numarası yapılandırılmamış.")
            return
        try:
            if self._use_http:
                await self._connect_http()
            else:
                await self._connect_socket()
        except Exception as exc:
            logger.error(f"Signal bağlantı hatası: {exc}")

    async def _connect_http(self):
        self._session = aiohttp.ClientSession()
        # Bağlantıyı doğrula
        async with self._session.get(f"{self.http_url}/v1/accounts") as resp:
            if resp.status == 200:
                self._is_connected = True
                logger.info(f"Signal HTTP proxy bağlandı: {self.http_url}")
                # Polling loop başlat
                self._poll_task = asyncio.create_task(self._poll_messages_http())
            else:
                logger.error(f"Signal HTTP bağlantı başarısız: {resp.status}")

    async def _connect_socket(self):
        if not os.path.exists(self.socket_path):
            logger.error(f"signald socket bulunamadı: {self.socket_path}")
            return
        self._is_connected = True
        logger.info(f"Signal unix socket bağlandı: {self.socket_path}")
        self._poll_task = asyncio.create_task(self._poll_messages_socket())

    async def disconnect(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        self._is_connected = False
        logger.info("Signal adapter kapatıldı.")

    # ── Polling — HTTP ────────────────────────────────────────────────────────

    async def _poll_messages_http(self):
        """signald HTTP proxy üzerinden mesaj polling (long-poll veya SSE)."""
        while self._is_connected:
            try:
                url = f"{self.http_url}/v1/receive/{self.phone_number}"
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for envelope in data if isinstance(data, list) else [data]:
                            await self._process_envelope(envelope)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Signal polling hatası: {exc}")
                await asyncio.sleep(5)

    # ── Polling — Socket ─────────────────────────────────────────────────────

    async def _poll_messages_socket(self):
        """signald unix socket üzerinden mesaj okuma."""
        while self._is_connected:
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path)
                # Subscribe isteği gönder
                subscribe_msg = json.dumps({
                    "type": "subscribe",
                    "account": self.phone_number
                }) + "\n"
                writer.write(subscribe_msg.encode())
                await writer.drain()

                while self._is_connected:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        payload = json.loads(line.decode())
                        await self._process_envelope(payload)
                    except json.JSONDecodeError:
                        pass
                writer.close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Signal socket hatası: {exc}")
                await asyncio.sleep(5)

    # ── Envelope Dispatch ─────────────────────────────────────────────────────

    async def _process_envelope(self, envelope: dict):
        """Gelen signald envelope'u UnifiedMessage'a dönüştür."""
        try:
            # signald mesaj formatı: envelope.data.dataMessage
            data = envelope.get("data", envelope)
            msg_data = data.get("dataMessage") or data.get("syncMessage", {}).get("sentMessage", {})
            if not msg_data:
                return
            body = msg_data.get("message") or msg_data.get("body", "")
            if not body:
                return

            source = data.get("source") or data.get("account", self.phone_number)
            group_info = msg_data.get("groupInfo") or msg_data.get("groupV2")
            channel_id = group_info.get("groupId", source) if group_info else source

            msg = UnifiedMessage(
                id=str(data.get("timestamp", "")),
                channel_type="signal",
                channel_id=channel_id,
                user_id=source,
                user_name=source,
                text=body,
                metadata={"group": bool(group_info)},
            )
            if self.on_message_callback:
                await self.on_message_callback(msg)
        except Exception as exc:
            logger.error(f"Signal envelope işleme hatası: {exc}")

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        try:
            if self._use_http and self._session:
                await self._send_http(chat_id, response.text)
            else:
                await self._send_socket(chat_id, response.text)
        except Exception as exc:
            logger.error(f"Signal gönderme hatası: {exc}")

    async def _send_http(self, recipient: str, text: str):
        payload = {
            "message": text,
            "number": self.phone_number,
            "recipients": [recipient],
        }
        post_ctx = self._session.post(f"{self.http_url}/v2/send", json=payload)
        if asyncio.iscoroutine(post_ctx):
            post_ctx = await post_ctx
        async with post_ctx as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                logger.error(f"Signal HTTP gönderim hatası {resp.status}: {body}")

    async def _send_socket(self, recipient: str, text: str):
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        send_msg = json.dumps({
            "type": "send",
            "username": self.phone_number,
            "recipientAddress": {"number": recipient},
            "messageBody": text,
        }) + "\n"
        writer.write(send_msg.encode())
        await writer.drain()
        writer.close()

    # ── Status / Capabilities ─────────────────────────────────────────────────

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "text": True,
            "images": True,
            "voice": True,
            "markdown": False,
            "buttons": False,
            "groups": True,
        }
