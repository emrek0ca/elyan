from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import aiohttp
import os
import tempfile
from typing import Dict, Any
from pathlib import Path
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("slack_adapter")

class SlackAdapter(BaseChannelAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.app_token = config.get("app_token")
        self.bot_token = config.get("bot_token")
        self.app = AsyncApp(token=self.bot_token)
        self.handler = None
        self._is_connected = False

        @self.app.event("message")
        async def handle_message_events(event, say):
            if event.get("bot_id"): return # Ignore bot messages

            msg = await self._build_unified_message(event)
            if self.on_message_callback:
                await self.on_message_callback(msg)

    @staticmethod
    def _is_audio_file(file_payload: Dict[str, Any]) -> bool:
        mime = str(file_payload.get("mimetype") or "").strip().lower()
        filetype = str(file_payload.get("filetype") or "").strip().lower()
        name = str(file_payload.get("name") or "").strip().lower()
        return mime.startswith("audio/") or filetype in {"wav", "mp3", "m4a", "ogg", "webm"} or name.endswith((".wav", ".mp3", ".m4a", ".ogg", ".webm"))

    @staticmethod
    def _compose_text(text: str, transcript: str) -> str:
        raw = str(text or "").strip()
        transcribed = str(transcript or "").strip()
        if raw and transcribed:
            return f"{raw}\n\nVoice transcript:\n{transcribed}"
        return transcribed or raw

    async def _download_slack_file(self, url: str, suffix: str) -> str:
        headers = {"Authorization": f"Bearer {self.bot_token}"} if self.bot_token else {}
        with tempfile.NamedTemporaryFile(prefix="elyan_slack_", suffix=suffix or ".bin", delete=False) as tmp:
            tmp_path = tmp.name
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Slack file download failed: HTTP {resp.status}")
                payload = await resp.read()
        Path(tmp_path).write_bytes(payload or b"")
        return tmp_path

    async def _transcribe_slack_file(self, file_payload: Dict[str, Any]) -> tuple[str, str]:
        url = str(file_payload.get("url_private_download") or file_payload.get("url_private") or "").strip()
        if not url:
            return "", ""
        suffix = Path(str(file_payload.get("name") or "voice-note")).suffix or ".bin"
        tmp_path = ""
        try:
            tmp_path = await self._download_slack_file(url, suffix)
            from core.voice.stt_engine import get_stt_engine

            transcript = await get_stt_engine().transcribe_async(tmp_path)
            return tmp_path, str(transcript or "").strip()
        except Exception as exc:
            logger.warning(f"Slack audio transcription failed: {exc}")
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            return "", ""

    async def _build_unified_message(self, event: Dict[str, Any]) -> UnifiedMessage:
        attachments = []
        transcript = ""
        for file_payload in list(event.get("files") or []):
            if not isinstance(file_payload, dict) or not self._is_audio_file(file_payload):
                continue
            path, transcript = await self._transcribe_slack_file(file_payload)
            if path:
                attachments.append(
                    {
                        "type": "audio",
                        "path": path,
                        "name": str(file_payload.get("name") or Path(path).name),
                        "mime": str(file_payload.get("mimetype") or ""),
                    }
                )
            if transcript:
                break
        return UnifiedMessage(
            id=str(event.get("ts") or ""),
            channel_type="slack",
            channel_id=str(event.get("channel") or ""),
            user_id=str(event.get("user") or ""),
            user_name=str(event.get("user") or ""),
            text=self._compose_text(str(event.get("text") or ""), transcript),
            attachments=attachments,
            metadata={"is_voice": bool(transcript), "voice_transcript": transcript} if transcript else {},
        )

    async def connect(self):
        if not self.app_token or not self.bot_token:
            logger.error("Slack tokens missing.")
            return

        try:
            self.handler = AsyncSocketModeHandler(self.app, self.app_token)
            await self.handler.connect_async()
            self._is_connected = True
            logger.info("Slack adapter connected via Socket Mode.")
        except Exception as exc:
            self._is_connected = False
            logger.error(f"Slack connect failed: {exc}")
            raise

    async def disconnect(self):
        if self.handler:
            await self.handler.close_async()
        self._is_connected = False

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        try:
            await self.app.client.chat_postMessage(
                channel=chat_id,
                text=response.text
            )
            for attachment in list(getattr(response, "attachments", []) or []):
                if not isinstance(attachment, dict):
                    continue
                path = str(attachment.get("path") or "").strip()
                if not path or not Path(path).exists():
                    continue
                title = str(attachment.get("name") or Path(path).name)
                try:
                    upload = getattr(self.app.client, "files_upload_v2", None)
                    if callable(upload):
                        await upload(channel=chat_id, file=path, title=title)
                except Exception as upload_exc:
                    logger.warning(f"Slack attachment upload failed ({path}): {upload_exc}")
        except Exception as e:
            self._is_connected = False
            logger.error(f"Failed to send Slack message: {e}")
            raise

    def get_status(self) -> str:
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {"buttons": True, "threads": True, "markdown": True, "images": True, "files": True, "voice": True}
