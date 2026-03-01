"""
Microsoft Teams Adapter — Azure Bot Framework + aiohttp webhook.

Yaklaşım:
  1. Azure'da "Bot Channels Registration" oluşturulur
  2. Bot Framework messaging endpoint: http(s)://host:PORT/api/teams/messages
  3. ElyanGatewayServer bu endpoint'i açar; Teams'den gelen Activity nesneleri işlenir
  4. Yanıtlar Bot Framework REST API üzerinden gönderilir

Gereksinimler:
  pip install botbuilder-core botbuilder-schema

Yapılandırma (elyan.json):
  {
    "type": "teams",
    "app_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "app_password": "...",
    "webhook_path": "/api/teams/messages"  # default
  }
"""
import asyncio
import hmac
import hashlib
import json
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import web

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("teams_adapter")

BOT_FRAMEWORK_ENDPOINT = "https://smba.trafficmanager.net/apis"


class TeamsAdapter(BaseChannelAdapter):
    """
    Microsoft Teams kanal adaptörü.
    Azure Bot Framework webhook modeli ile çalışır.

    Desteklenen özellikler:
    - Metin mesajları (kişisel/grup/kanal)
    - Adaptive Cards (JSON)
    - Mention / @elyan
    - Replies (conversation reference korunur)
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_id: str = config.get("app_id", "")
        self.app_password: str = config.get("app_password", "")
        self.webhook_path: str = config.get("webhook_path", "/api/teams/messages")
        self._bearer_token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self._is_connected: bool = False
        # conversation_id -> serviceUrl (Teams yanıt için gerekli)
        self._service_urls: Dict[str, str] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        if not self.app_id or not self.app_password:
            logger.error("Teams: app_id veya app_password yapılandırılmamış.")
            return
        self._session = aiohttp.ClientSession()
        # Token al (yanıt gönderebilmek için)
        await self._refresh_token()
        self._is_connected = bool(self._bearer_token)
        if self._is_connected:
            logger.info(f"Teams adapter hazır (webhook: {self.webhook_path})")
        else:
            logger.error("Teams: Bearer token alınamadı.")

    async def disconnect(self):
        if self._session:
            await self._session.close()
        self._is_connected = False
        logger.info("Teams adapter kapatıldı.")

    # ── Token Yönetimi ───────────────────────────────────────────────────────

    async def _refresh_token(self):
        """Azure AD'den Bot Framework bearer token al."""
        import time
        url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.app_id,
            "client_secret": self.app_password,
            "scope": "https://api.botframework.com/.default",
        }
        try:
            async with self._session.post(url, data=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._bearer_token = data.get("access_token")
                    self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
                    logger.debug("Teams bearer token yenilendi.")
                else:
                    body = await resp.text()
                    logger.error(f"Teams token hatası {resp.status}: {body}")
        except Exception as exc:
            logger.error(f"Teams token isteği hatası: {exc}")

    async def _ensure_token(self):
        import time
        if time.time() >= self._token_expiry:
            await self._refresh_token()

    # ── Webhook Handler ──────────────────────────────────────────────────────

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """
        aiohttp route handler — ElyanGatewayServer tarafından kayıt edilir.
        Teams bu endpoint'e Activity nesnesi POSTlar.
        """
        try:
            body_bytes = await request.read()
            activity = json.loads(body_bytes)

            # Sadece message activity'leri işle
            if activity.get("type") != "message":
                return web.Response(status=202)

            channel_id = activity.get("conversation", {}).get("id", "")
            service_url = activity.get("serviceUrl", BOT_FRAMEWORK_ENDPOINT)
            self._service_urls[channel_id] = service_url

            # @mention temizle
            text = activity.get("text", "")
            if text:
                # <at>Bot</at> etiketlerini kaldır
                import re
                text = re.sub(r"<at>[^<]*</at>", "", text).strip()

            sender = activity.get("from", {})
            msg = UnifiedMessage(
                id=activity.get("id", ""),
                channel_type="teams",
                channel_id=channel_id,
                user_id=sender.get("id", ""),
                user_name=sender.get("name", ""),
                text=text,
                metadata={
                    "conversation_type": activity.get("conversation", {}).get("conversationType"),
                    "service_url": service_url,
                    "tenant_id": activity.get("channelData", {}).get("tenant", {}).get("id"),
                    "reply_to_id": activity.get("id"),
                },
            )
            if self.on_message_callback:
                callback_result = self.on_message_callback(msg)
                if asyncio.iscoroutine(callback_result):
                    asyncio.create_task(callback_result)

            return web.Response(status=202)

        except Exception as exc:
            logger.error(f"Teams webhook işleme hatası: {exc}")
            return web.Response(status=500)

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if not self._session:
            logger.error("Teams session yok.")
            raise RuntimeError("Teams session yok")
        await self._ensure_token()
        service_url = self._service_urls.get(chat_id, BOT_FRAMEWORK_ENDPOINT)
        url = f"{service_url}/v3/conversations/{chat_id}/activities"

        activity = {
            "type": "message",
            "text": response.text,
            "textFormat": "markdown",
        }
        try:
            async with self._session.post(
                url,
                json=activity,
                headers={"Authorization": f"Bearer {self._bearer_token}"},
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(f"Teams gönderme hatası {resp.status}: {body}")
                    raise RuntimeError(f"Teams HTTP {resp.status}: {body[:240]}")
        except Exception as exc:
            logger.error(f"Teams send hatası: {exc}")
            raise

    # ── Status / Capabilities ─────────────────────────────────────────────────

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "text": True,
            "markdown": True,
            "adaptive_cards": True,
            "buttons": True,
            "images": True,
            "threads": True,
            "groups": True,
        }
