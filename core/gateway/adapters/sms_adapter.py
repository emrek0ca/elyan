from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import web

from utils.logger import get_logger

from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse

logger = get_logger("sms_adapter")


class SmsAdapter(BaseChannelAdapter):
    """Twilio-backed SMS adapter with REST send + webhook receive."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.account_sid = str(config.get("account_sid") or "").strip()
        self.auth_token = str(config.get("auth_token") or config.get("token") or "").strip()
        self.from_number = str(config.get("from_number") or config.get("phone_number") or "").strip()
        self.webhook_path = str(config.get("webhook_path") or "/sms/webhook").strip() or "/sms/webhook"
        allowed_numbers = config.get("allowed_numbers", [])
        if isinstance(allowed_numbers, str):
            allowed_numbers = [chunk.strip() for chunk in allowed_numbers.split(",")]
        self.allowed_numbers = {str(item).strip() for item in list(allowed_numbers or []) if str(item).strip()}
        self._session: Optional[aiohttp.ClientSession] = None
        self._is_connected = False

    async def connect(self):
        if not self.account_sid or not self.auth_token or not self.from_number:
            logger.warning("SMS adapter missing Twilio credentials or from_number.")
            self._is_connected = False
            return
        self._session = aiohttp.ClientSession(
            auth=aiohttp.BasicAuth(login=self.account_sid, password=self.auth_token),
        )
        self._is_connected = True
        logger.info("SMS adapter ready via Twilio REST.")

    async def disconnect(self):
        if self._session:
            await self._session.close()
            self._session = None
        self._is_connected = False

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if not self._is_connected:
            await self.connect()
        if not self._session:
            raise RuntimeError("SMS adapter session unavailable.")
        to_number = str(chat_id or "").strip()
        text = str(getattr(response, "text", "") or "").strip()
        if not to_number:
            raise RuntimeError("SMS target number required.")
        if not text:
            raise RuntimeError("SMS body required.")

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = {
            "To": to_number,
            "From": self.from_number,
            "Body": text,
        }
        try:
            async with self._session.post(url, data=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status not in {200, 201}:
                    body = await resp.text()
                    raise RuntimeError(f"Twilio SMS HTTP {resp.status}: {body[:240]}")
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Twilio SMS timed out.") from exc

    def _twilio_signature_payload(self, request: web.Request, payload: Dict[str, Any]) -> bytes:
        data = str(request.url)
        for key, value in sorted((str(k), str(v)) for k, v in payload.items()):
            data += key + value
        digest = hmac.new(self.auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(digest)

    def _is_valid_twilio_signature(self, request: web.Request, payload: Dict[str, Any]) -> bool:
        signature = str(request.headers.get("X-Twilio-Signature") or "").strip()
        if not signature or not self.auth_token:
            return False
        expected = self._twilio_signature_payload(request, payload).decode("utf-8")
        return hmac.compare_digest(signature, expected)

    async def handle_webhook(self, request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.post()
        except Exception:
            return web.Response(status=400, text="invalid form payload")
        payload_dict = {str(key): str(value) for key, value in payload.items()}

        if not self._is_valid_twilio_signature(request, payload_dict):
            return web.Response(status=403, text="invalid_signature")

        from_number = str(payload_dict.get("From") or "").strip()
        body = str(payload_dict.get("Body") or "").strip()
        message_sid = str(payload_dict.get("MessageSid") or payload_dict.get("SmsSid") or "").strip()

        if self.allowed_numbers and from_number not in self.allowed_numbers:
            return web.Response(status=403, text="sender_not_allowed")
        if not body:
            return web.Response(text="<Response></Response>", content_type="text/xml")

        unified = UnifiedMessage(
            id=message_sid or f"sms-{int(asyncio.get_running_loop().time() * 1000)}",
            channel_type="sms",
            channel_id=from_number,
            user_id=from_number,
            user_name=from_number,
            text=body,
            metadata={
                "source": "twilio_webhook",
                "from_number": from_number,
                "to_number": str(payload_dict.get("To") or "").strip(),
            },
        )
        if self.on_message_callback:
            await self.on_message_callback(unified)
        return web.Response(text="<Response></Response>", content_type="text/xml")

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "markdown": False,
            "html": False,
            "buttons": False,
            "images": False,
            "files": False,
            "text": True,
        }
