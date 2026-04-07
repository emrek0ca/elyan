import asyncio
import mimetypes
from pathlib import Path
import re
from typing import Any, Dict, Optional, List

import httpx
from aiohttp import web

from config.elyan_config import elyan_config
from utils.logger import get_logger
from .base import BaseChannelAdapter
from .whatsapp_bridge import (
    BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    BridgeRuntimeError,
    bridge_health,
    bridge_request,
    build_bridge_url,
    default_session_dir,
    start_bridge_process,
    wait_for_bridge,
)
from ..message import UnifiedMessage
from ..response import UnifiedResponse

logger = get_logger("whatsapp_adapter")


def _resolve_secret_value(value: Any) -> str:
    return str(elyan_config._resolve_secret_ref(value) or "").strip()


class WhatsAppAdapter(BaseChannelAdapter):
    """WhatsApp adapter supporting local bridge and Cloud API webhook mode."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._is_connected = False
        self._mode = str(config.get("mode") or "bridge").strip().lower() or "bridge"
        self._poll_task: Optional[asyncio.Task] = None
        self._bridge_process = None
        self._bridge_owned = False
        self._image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        self._max_auto_files = max(1, min(5, int(config.get("auto_send_files_max", 3))))

        # Bridge mode config
        self._bridge_url = str(
            config.get("bridge_url")
            or build_bridge_url(
                host=str(config.get("bridge_host", BRIDGE_HOST)),
                port=int(config.get("bridge_port", DEFAULT_BRIDGE_PORT)),
            )
        ).rstrip("/")
        self._bridge_token = _resolve_secret_value(config.get("bridge_token"))
        self._session_dir = Path(
            str(config.get("session_dir") or default_session_dir(str(config.get("id") or "default")))
        ).expanduser()
        self._client_id = str(config.get("client_id") or str(config.get("id") or "default"))
        self._auto_start_bridge = bool(config.get("auto_start_bridge", True))
        self._incoming_backoff_s = float(config.get("incoming_poll_interval_sec", 1.2))

        # Cloud mode config
        self._graph_base_url = str(config.get("graph_base_url") or "https://graph.facebook.com/v20.0").rstrip("/")
        self._phone_number_id = str(config.get("phone_number_id") or "").strip()
        self._access_token = _resolve_secret_value(config.get("access_token"))
        self._verify_token = _resolve_secret_value(config.get("verify_token"))
        allowed = config.get("allowed_senders", [])
        if not isinstance(allowed, list):
            allowed = []
        self._allowed_senders = {str(x).strip() for x in allowed if str(x).strip()}

    async def connect(self):
        if self._is_connected:
            return

        if self._mode == "cloud":
            if not self._phone_number_id:
                raise RuntimeError("WhatsApp Cloud mode: phone_number_id eksik.")
            if not self._access_token or self._access_token.startswith("$"):
                raise RuntimeError("WhatsApp Cloud mode: access_token eksik.")
            self._is_connected = True
            logger.info("WhatsApp adapter connected via Cloud API mode.")
            return

        if not self._bridge_token or self._bridge_token.startswith("$"):
            raise RuntimeError("WhatsApp bridge token çözümlenemedi.")

        if self._auto_start_bridge:
            await self._ensure_bridge_running()

        state = await self._get_bridge_state()
        if not bool(state.get("ready")):
            self._is_connected = False
            raise RuntimeError(
                "WhatsApp bridge hazır değil. QR eşleşmesi için: `elyan channels login whatsapp`"
            )

        self._is_connected = True
        if not self._poll_task or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_incoming_loop(), name="whatsapp-incoming-poll")
        logger.info("WhatsApp adapter connected via local bridge.")

    async def disconnect(self):
        self._is_connected = False
        if self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None

        if self._bridge_owned and self._bridge_process:
            try:
                self._bridge_process.terminate()
            except Exception:
                pass
            self._bridge_process = None
            self._bridge_owned = False

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if not self._is_connected:
            await self.connect()

        text = str(getattr(response, "text", "") or "").strip()
        files = self._collect_local_files(response, text)[: self._max_auto_files]
        used_caption = False

        if self._mode == "cloud":
            for idx, file_path in enumerate(files):
                caption = text if text and idx == 0 else ""
                try:
                    await self._send_cloud_media(chat_id=chat_id, file_path=file_path, caption=caption)
                    if caption:
                        used_caption = True
                except Exception as exc:
                    logger.warning(f"WhatsApp cloud media send failed ({file_path}): {exc}")
            if text and not used_caption:
                await self._send_cloud_message(chat_id=chat_id, text=text)
            return

        for idx, file_path in enumerate(files):
            caption = text if text and idx == 0 else ""
            try:
                await self._send_bridge_media(chat_id=chat_id, file_path=file_path, caption=caption)
                if caption:
                    used_caption = True
            except Exception as exc:
                logger.warning(f"WhatsApp bridge media send failed ({file_path}): {exc}")

        if text and not used_caption:
            await self._bridge_call(
                method="POST",
                path="/send",
                payload={"to": str(chat_id or "").strip(), "text": text},
            )

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "images": True,
            "voice": False,
            "markdown": False,
            "files": True,
        }

    @staticmethod
    def _extract_local_paths(text: str) -> List[str]:
        raw = str(text or "")
        if not raw:
            return []

        pattern = re.compile(r"((?:~|/)[^\n\r\t]*?\.[a-z0-9]{1,8})", re.IGNORECASE)
        paths: list[str] = []
        seen: set[str] = set()
        for m in pattern.finditer(raw):
            candidate = str(m.group(1) or "").strip(" \t\r\n\"'`.,;:)]}")
            if not candidate or "://" in candidate:
                continue
            try:
                p = Path(candidate).expanduser()
            except Exception:
                continue
            if not p.is_file():
                continue
            s = str(p)
            if s in seen:
                continue
            seen.add(s)
            paths.append(s)
        return paths

    def _collect_local_files(self, response: UnifiedResponse, text_payload: str) -> List[str]:
        files: list[str] = []
        seen: set[str] = set()
        for attachment in (getattr(response, "attachments", None) or []):
            if not isinstance(attachment, dict):
                continue
            raw_path = str(attachment.get("path") or attachment.get("file_path") or "").strip()
            if not raw_path:
                continue
            try:
                p = Path(raw_path).expanduser()
            except Exception:
                continue
            if not p.is_file():
                continue
            s = str(p)
            if s in seen:
                continue
            seen.add(s)
            files.append(s)

        for raw in self._extract_local_paths(text_payload):
            if raw in seen:
                continue
            seen.add(raw)
            files.append(raw)
        return files

    async def _send_cloud_message(self, chat_id: str, text: str) -> None:
        to = self._normalize_cloud_chat_id(chat_id)
        if not to:
            raise RuntimeError("WhatsApp Cloud mode: hedef chat_id geçersiz.")

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        await self._send_cloud_payload(payload)

    async def _send_cloud_payload(self, payload: Dict[str, Any]) -> None:
        url = f"{self._graph_base_url}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 300:
                body = (resp.text or "").strip()
                raise RuntimeError(f"WhatsApp Cloud API HTTP {resp.status_code}: {body[:240]}")

    def _guess_mime_type(self, file_path: Path) -> str:
        mime, _ = mimetypes.guess_type(str(file_path))
        return str(mime or "application/octet-stream")

    async def _upload_cloud_media(self, file_path: Path) -> str:
        url = f"{self._graph_base_url}/{self._phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        mime = self._guess_mime_type(file_path)
        data = {"messaging_product": "whatsapp", "type": mime}
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh, mime)}
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, headers=headers, data=data, files=files)
        if resp.status_code >= 300:
            body = (resp.text or "").strip()
            raise RuntimeError(f"WhatsApp Cloud media upload HTTP {resp.status_code}: {body[:240]}")
        payload = resp.json() if resp.content else {}
        media_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
        if not media_id:
            raise RuntimeError("WhatsApp Cloud media upload id döndürmedi.")
        return media_id

    async def _send_cloud_media(self, chat_id: str, file_path: str, caption: str = "") -> None:
        to = self._normalize_cloud_chat_id(chat_id)
        if not to:
            raise RuntimeError("WhatsApp Cloud mode: hedef chat_id geçersiz.")

        path = Path(str(file_path or "")).expanduser()
        if not path.is_file():
            raise RuntimeError(f"WhatsApp Cloud mode: dosya bulunamadı: {path}")

        media_id = await self._upload_cloud_media(path)
        mime = self._guess_mime_type(path)
        payload: Dict[str, Any] = {"messaging_product": "whatsapp", "to": to}
        if mime.startswith("image/"):
            payload["type"] = "image"
            payload["image"] = {"id": media_id}
            if caption:
                payload["image"]["caption"] = caption[:900]
        else:
            payload["type"] = "document"
            payload["document"] = {"id": media_id, "filename": path.name}
            if caption:
                payload["document"]["caption"] = caption[:900]

        await self._send_cloud_payload(payload)

    async def _send_bridge_media(self, chat_id: str, file_path: str, caption: str = "") -> None:
        path = Path(str(file_path or "")).expanduser()
        if not path.is_file():
            raise RuntimeError(f"WhatsApp bridge mode: dosya bulunamadı: {path}")
        payload = {
            "to": str(chat_id or "").strip(),
            "path": str(path),
            "caption": str(caption or "")[:900],
        }
        await self._bridge_call(method="POST", path="/send-media", payload=payload)

    @staticmethod
    def _normalize_cloud_chat_id(chat_id: str) -> str:
        raw = str(chat_id or "").strip()
        if not raw:
            return ""
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits

    async def handle_webhook_verification(self, request: web.Request) -> web.StreamResponse:
        if self._mode != "cloud":
            return web.Response(text="whatsapp mode is bridge", status=400)

        mode = str(request.query.get("hub.mode") or "").strip().lower()
        token = str(request.query.get("hub.verify_token") or "").strip()
        challenge = str(request.query.get("hub.challenge") or "").strip()

        if mode == "subscribe" and token and token == self._verify_token:
            return web.Response(text=challenge or "ok", status=200)
        return web.Response(text="forbidden", status=403)

    async def handle_webhook(self, request: web.Request) -> web.StreamResponse:
        if self._mode != "cloud":
            return web.json_response({"ok": False, "error": "whatsapp mode is bridge"}, status=400)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        processed = 0
        ignored = 0

        for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []) if isinstance(entry.get("changes"), list) else []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue

                contacts = value.get("contacts", []) if isinstance(value.get("contacts"), list) else []
                names = {}
                for c in contacts:
                    if not isinstance(c, dict):
                        continue
                    wa_id = str(c.get("wa_id") or "").strip()
                    profile = c.get("profile", {})
                    pname = ""
                    if isinstance(profile, dict):
                        pname = str(profile.get("name") or "").strip()
                    if wa_id:
                        names[wa_id] = pname

                messages = value.get("messages", []) if isinstance(value.get("messages"), list) else []
                for msg in messages:
                    if not isinstance(msg, dict):
                        ignored += 1
                        continue
                    from_id = str(msg.get("from") or "").strip()
                    if not from_id:
                        ignored += 1
                        continue
                    if self._allowed_senders and from_id not in self._allowed_senders:
                        ignored += 1
                        continue

                    mtype = str(msg.get("type") or "").strip().lower()
                    text = ""
                    if mtype == "text":
                        text = str((msg.get("text") or {}).get("body") or "").strip()
                    elif mtype == "interactive":
                        interactive = msg.get("interactive", {})
                        if isinstance(interactive, dict):
                            text = str((interactive.get("button_reply") or {}).get("title") or "").strip()
                            if not text:
                                text = str((interactive.get("list_reply") or {}).get("title") or "").strip()
                    elif mtype == "button":
                        text = str((msg.get("button") or {}).get("text") or "").strip()

                    if not text:
                        ignored += 1
                        continue

                    user_name = names.get(from_id) or from_id
                    unified = UnifiedMessage(
                        id=str(msg.get("id") or ""),
                        channel_type="whatsapp",
                        channel_id=from_id,
                        user_id=from_id,
                        user_name=user_name,
                        text=text,
                        metadata={
                            "type": mtype,
                            "timestamp": msg.get("timestamp"),
                            "cloud": True,
                        },
                    )
                    if self.on_message_callback:
                        callback_result = self.on_message_callback(unified)
                        if asyncio.iscoroutine(callback_result):
                            await callback_result
                    processed += 1

        return web.json_response({"ok": True, "processed": processed, "ignored": ignored})

    async def _ensure_bridge_running(self):
        try:
            await asyncio.to_thread(bridge_health, self._bridge_url, self._bridge_token, 1.5)
            return
        except Exception:
            pass

        try:
            self._bridge_process = start_bridge_process(
                session_dir=self._session_dir,
                token=self._bridge_token,
                host=str(self.config.get("bridge_host", BRIDGE_HOST)),
                port=int(self.config.get("bridge_port", DEFAULT_BRIDGE_PORT)),
                print_qr=False,
                detached=True,
                client_id=self._client_id,
            )
            self._bridge_owned = True
            await asyncio.to_thread(
                wait_for_bridge,
                self._bridge_url,
                self._bridge_token,
                25,
                False,
                1.0,
            )
        except BridgeRuntimeError as exc:
            raise RuntimeError(f"WhatsApp bridge başlatılamadı: {exc}") from exc

    async def _get_bridge_state(self) -> Dict[str, Any]:
        try:
            health = await asyncio.to_thread(bridge_health, self._bridge_url, self._bridge_token, 2.5)
            state = health.get("state", {}) if isinstance(health, dict) else {}
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    async def _bridge_call(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        code, data = await asyncio.to_thread(
            bridge_request,
            bridge_url=self._bridge_url,
            method=method,
            path=path,
            token=self._bridge_token,
            payload=payload,
            timeout_s=10.0,
        )
        if code >= 400:
            msg = data.get("error") if isinstance(data, dict) else str(data)
            raise RuntimeError(f"WhatsApp bridge HTTP {code}: {msg}")
        return data if isinstance(data, dict) else {}

    async def _poll_incoming_loop(self):
        while self._is_connected:
            try:
                data = await self._bridge_call("GET", "/messages")
                items = data.get("items", []) if isinstance(data, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if bool(item.get("fromMe")):
                        continue
                    text = str(item.get("body") or "").strip()
                    if not text:
                        continue
                    msg = UnifiedMessage(
                        id=str(item.get("id") or ""),
                        channel_type="whatsapp",
                        channel_id=str(item.get("from") or ""),
                        user_id=str(item.get("from") or ""),
                        user_name=str(item.get("pushName") or item.get("from") or "WhatsApp User"),
                        text=text,
                        metadata={
                            "type": item.get("type", "chat"),
                            "timestamp": item.get("timestamp"),
                            "is_group": bool(item.get("isGroup", False)),
                        },
                    )
                    if self.on_message_callback:
                        await self.on_message_callback(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"WhatsApp incoming poll error: {exc}")
                self._is_connected = False
                break

            await asyncio.sleep(max(0.5, self._incoming_backoff_s))
