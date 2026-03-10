from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
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
            
            msg = UnifiedMessage(
                id=event.get("ts"),
                channel_type="slack",
                channel_id=event.get("channel"),
                user_id=event.get("user"),
                user_name=event.get("user"), # Ideally fetch user info
                text=event.get("text", "")
            )
            
            if self.on_message_callback:
                await self.on_message_callback(msg)

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
        return {"buttons": True, "threads": True, "markdown": True, "images": True, "files": True}
