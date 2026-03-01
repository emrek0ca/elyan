"""
Google Chat Adapter — Google Chat API (Pub/Sub ve HTTP webhook).

İki mod:
  1. Webhook mod (basit, tek yönlü): Incoming webhook URL ile mesaj gönderme
  2. Bot mod (tam özellik): Google Cloud Pub/Sub aboneliği ile mesaj alma + gönderme

Gereksinimler (Bot mod):
  pip install google-cloud-pubsub google-auth

Yapılandırma (elyan.json):
  # Webhook modu (yalnızca gönderme):
  {
    "type": "google_chat",
    "mode": "webhook",
    "webhook_url": "https://chat.googleapis.com/v1/spaces/.../messages?key=..."
  }

  # Bot modu (tam):
  {
    "type": "google_chat",
    "mode": "bot",
    "project_id": "my-gcp-project",
    "subscription_id": "elyan-chat-sub",
    "service_account_file": "/path/to/service_account.json",
    "webhook_path": "/api/google_chat/messages"
  }
"""
import asyncio
import json
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import web

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("google_chat_adapter")

GOOGLE_CHAT_API = "https://chat.googleapis.com/v1"


class GoogleChatAdapter(BaseChannelAdapter):
    """
    Google Chat kanal adaptörü.
    Webhook modu (kolay kurulum) veya Bot modu (tam özellik) ile çalışır.

    Desteklenen özellikler:
    - DM ve Space (grup) mesajları
    - Card mesajları (bot modu)
    - Thread desteği
    - Mention / @Elyan
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.mode: str = config.get("mode", "webhook")  # webhook | bot
        # Webhook modu
        self.webhook_url: str = config.get("webhook_url", "")
        # Bot modu
        self.project_id: str = config.get("project_id", "")
        self.subscription_id: str = config.get("subscription_id", "")
        self.service_account_file: str = config.get("service_account_file", "")
        self.webhook_path: str = config.get("webhook_path", "/api/google_chat/messages")
        # HTTP için oturum
        self._session: Optional[aiohttp.ClientSession] = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._bearer_token: Optional[str] = None
        self._is_connected: bool = False
        # space_name -> thread_name (son thread'i sürdür)
        self._last_threads: Dict[str, str] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        self._session = aiohttp.ClientSession()

        if self.mode == "webhook":
            if not self.webhook_url:
                logger.error("Google Chat webhook modu: webhook_url eksik.")
                return
            self._is_connected = True
            logger.info("Google Chat webhook modu aktif (yalnızca gönderme).")

        elif self.mode == "bot":
            if not self.service_account_file:
                logger.error("Google Chat bot modu: service_account_file eksik.")
                return
            await self._authenticate()
            if self._bearer_token:
                self._is_connected = True
                logger.info(f"Google Chat bot bağlandı (proje: {self.project_id})")
                # Pub/Sub mesaj dinleme başlat
                self._pubsub_task = asyncio.create_task(self._pubsub_loop())
        else:
            logger.error(f"Google Chat bilinmeyen mod: {self.mode}")

    async def disconnect(self):
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        self._is_connected = False
        logger.info("Google Chat adapter kapatıldı.")

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _authenticate(self):
        """Google service account ile OAuth2 token al."""
        try:
            import google.auth
            import google.auth.transport.requests
            from google.oauth2 import service_account

            scopes = ["https://www.googleapis.com/auth/chat.bot"]
            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=scopes
            )
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            self._bearer_token = creds.token
            logger.debug("Google Chat service account token alındı.")
        except ImportError:
            logger.error("google-auth kurulu değil. 'pip install google-auth' çalıştırın.")
        except Exception as exc:
            logger.error(f"Google Chat kimlik doğrulama hatası: {exc}")

    # ── Pub/Sub Dinleyici ────────────────────────────────────────────────────

    async def _pubsub_loop(self):
        """Google Cloud Pub/Sub aboneliğinden mesaj al."""
        try:
            from google.cloud import pubsub_v1
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file
            )
            subscriber = pubsub_v1.SubscriberClient(credentials=creds)
            subscription_path = subscriber.subscription_path(
                self.project_id, self.subscription_id
            )

            def _callback(message):
                try:
                    data = json.loads(message.data.decode("utf-8"))
                    asyncio.run_coroutine_threadsafe(
                        self._process_event(data), asyncio.get_event_loop()
                    )
                    message.ack()
                except Exception as exc:
                    logger.error(f"Pub/Sub callback hatası: {exc}")
                    message.nack()

            future = subscriber.subscribe(subscription_path, callback=_callback)
            logger.info(f"Google Chat Pub/Sub dinleniyor: {subscription_path}")
            try:
                await asyncio.get_event_loop().run_in_executor(None, future.result)
            except asyncio.CancelledError:
                future.cancel()
        except ImportError:
            logger.error("google-cloud-pubsub kurulu değil.")
        except Exception as exc:
            logger.error(f"Google Chat Pub/Sub hatası: {exc}")

    # ── Event Dispatch ───────────────────────────────────────────────────────

    async def _process_event(self, event: dict):
        """Google Chat event'i UnifiedMessage'a dönüştür."""
        try:
            event_type = event.get("type", "")
            if event_type not in ("MESSAGE", "ADDED_TO_SPACE"):
                return

            msg_obj = event.get("message", {})
            text = msg_obj.get("argumentText") or msg_obj.get("text", "")
            if not text:
                return
            text = text.strip()

            sender = msg_obj.get("sender", {})
            space = event.get("space", {})
            thread = msg_obj.get("thread", {})
            space_name = space.get("name", "")

            if thread.get("name"):
                self._last_threads[space_name] = thread["name"]

            msg = UnifiedMessage(
                id=msg_obj.get("name", ""),
                channel_type="google_chat",
                channel_id=space_name,
                user_id=sender.get("name", ""),
                user_name=sender.get("displayName", ""),
                text=text,
                metadata={
                    "space_type": space.get("type"),
                    "thread_name": thread.get("name"),
                },
            )
            if self.on_message_callback:
                await self.on_message_callback(msg)
        except Exception as exc:
            logger.error(f"Google Chat event işleme hatası: {exc}")

    # ── Webhook Handler (bot modu HTTP) ──────────────────────────────────────

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """aiohttp route — ElyanGatewayServer tarafından kaydedilir."""
        try:
            event = await request.json()
            await self._process_event(event)
            return web.json_response({"text": ""})
        except Exception as exc:
            logger.error(f"Google Chat webhook hatası: {exc}")
            return web.Response(status=500)

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        """
        chat_id = space name (spaces/xxxxxxx) veya DM space name.
        """
        if not self._session:
            raise RuntimeError("Google Chat session yok.")
        try:
            if self.mode == "webhook":
                await self._send_webhook(response.text)
            else:
                await self._send_api(chat_id, response.text)
        except Exception as exc:
            logger.error(f"Google Chat gönderme hatası: {exc}")
            raise

    async def _send_webhook(self, text: str):
        payload = {"text": text}
        post_ctx = self._session.post(self.webhook_url, json=payload)
        if asyncio.iscoroutine(post_ctx):
            post_ctx = await post_ctx
        async with post_ctx as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                logger.error(f"Google Chat webhook gönderim hatası {resp.status}: {body}")
                raise RuntimeError(f"Google Chat webhook HTTP {resp.status}: {body[:240]}")

    async def _send_api(self, space_name: str, text: str):
        url = f"{GOOGLE_CHAT_API}/{space_name}/messages"
        body: Dict[str, Any] = {"text": text}

        # Aynı thread'e yanıt ver (varsa)
        thread_name = self._last_threads.get(space_name)
        if thread_name:
            body["thread"] = {"name": thread_name}

        headers = {"Authorization": f"Bearer {self._bearer_token}"}
        post_ctx = self._session.post(url, json=body, headers=headers)
        if asyncio.iscoroutine(post_ctx):
            post_ctx = await post_ctx
        async with post_ctx as resp:
            if resp.status not in (200, 201):
                body_txt = await resp.text()
                logger.error(f"Google Chat API gönderim hatası {resp.status}: {body_txt}")
                raise RuntimeError(f"Google Chat API HTTP {resp.status}: {body_txt[:240]}")

    # ── Status / Capabilities ─────────────────────────────────────────────────

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "text": True,
            "cards": self.mode == "bot",
            "threads": True,
            "markdown": False,
            "buttons": self.mode == "bot",
            "groups": True,
        }
