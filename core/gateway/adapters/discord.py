import asyncio
import discord
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
            
            msg = UnifiedMessage(
                id=str(message.id),
                channel_type="discord",
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                user_name=message.author.name,
                text=message.content
            )
            
            if self.on_message_callback:
                await self.on_message_callback(msg)

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
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")

    def get_status(self) -> str:
        if self.client.is_closed():
            self._is_connected = False
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {"buttons": True, "images": True, "markdown": True}
