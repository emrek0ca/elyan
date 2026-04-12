import asyncio
import discord
import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from utils.logger import get_logger

logger = get_logger("discord_adapter")

class DiscordAdapter(BaseChannelAdapter):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token")
        # Intents are required for modern Discord bots
        intents = discord.Intents.default()
        intents.message_content = True 
        self.client = discord.Client(intents=intents)
        self._is_connected = False
        self._connect_task = None

        @self.client.event
        async def on_ready():
            self._is_connected = True
            logger.info(f"Discord adapter logged in as {self.client.user}")

        @self.client.event
        async def on_disconnect():
            self._is_connected = False
            logger.warning("Discord adapter disconnected.")

        @self.client.event
        async def on_resumed():
            self._is_connected = True
            logger.info("Discord adapter resumed session.")

        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                return

            msg = await self._build_unified_message(message)
            if self.on_message_callback:
                await self.on_message_callback(msg)

    @staticmethod
    def _is_audio_attachment(content_type: str, filename: str) -> bool:
        mime = str(content_type or "").strip().lower()
        name = str(filename or "").strip().lower()
        return mime.startswith("audio/") or name.endswith((".wav", ".mp3", ".m4a", ".ogg", ".webm"))

    @staticmethod
    def _compose_text(text: str, transcript: str) -> str:
        raw = str(text or "").strip()
        transcribed = str(transcript or "").strip()
        if raw and transcribed:
            return f"{raw}\n\nVoice transcript:\n{transcribed}"
        return transcribed or raw

    async def _transcribe_attachment(self, attachment: Any) -> tuple[str, str]:
        filename = str(getattr(attachment, "filename", "") or "voice-note").strip() or "voice-note"
        suffix = Path(filename).suffix or ".bin"
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="elyan_discord_", suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
            save = getattr(attachment, "save", None)
            if callable(save):
                maybe = save(tmp_path)
                if asyncio.iscoroutine(maybe):
                    await maybe
            elif hasattr(attachment, "read"):
                payload = attachment.read()
                if asyncio.iscoroutine(payload):
                    payload = await payload
                Path(tmp_path).write_bytes(payload or b"")
            else:
                return "", ""
            from core.voice.stt_engine import get_stt_engine

            transcript = await get_stt_engine().transcribe_async(tmp_path)
            return tmp_path, str(transcript or "").strip()
        except Exception as exc:
            logger.warning(f"Discord audio transcription failed: {exc}")
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            return "", ""

    async def _build_unified_message(self, message: Any) -> UnifiedMessage:
        attachments = []
        transcript = ""
        for attachment in list(getattr(message, "attachments", []) or []):
            if not self._is_audio_attachment(
                str(getattr(attachment, "content_type", "") or ""),
                str(getattr(attachment, "filename", "") or ""),
            ):
                continue
            path, transcript = await self._transcribe_attachment(attachment)
            if path:
                attachments.append(
                    {
                        "type": "audio",
                        "path": path,
                        "name": str(getattr(attachment, "filename", "") or Path(path).name),
                        "mime": str(getattr(attachment, "content_type", "") or ""),
                    }
                )
            if transcript:
                break
        return UnifiedMessage(
            id=str(message.id),
            channel_type="discord",
            channel_id=str(message.channel.id),
            user_id=str(message.author.id),
            user_name=message.author.name,
            text=self._compose_text(getattr(message, "content", ""), transcript),
            attachments=attachments,
            metadata={"is_voice": bool(transcript), "voice_transcript": transcript} if transcript else {},
        )

    async def connect(self):
        if not self.token:
            logger.error("No Discord token provided.")
            return
        if self._connect_task and not self._connect_task.done():
            return

        async def _runner():
            try:
                await self.client.start(self.token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._is_connected = False
                logger.error(f"Discord start failed: {exc}")
            finally:
                self._is_connected = False

        self._connect_task = asyncio.create_task(_runner(), name="discord-adapter-start")
        await asyncio.sleep(0)

    async def disconnect(self):
        try:
            await self.client.close()
        except Exception:
            pass
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            await asyncio.gather(self._connect_task, return_exceptions=True)
        self._connect_task = None
        self._is_connected = False

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        try:
            channel = self.client.get_channel(int(chat_id))
            if channel:
                await channel.send(response.text)
            else:
                raise RuntimeError(f"Discord channel not found: {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            raise

    def get_status(self) -> str:
        if self.client.is_closed():
            self._is_connected = False
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {"buttons": True, "images": True, "markdown": True, "voice": True, "files": True}
