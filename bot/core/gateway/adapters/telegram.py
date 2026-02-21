import asyncio
from typing import Dict, Any
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from tools.voice.local_stt import stt_engine
import os
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("telegram_adapter")

class TelegramAdapter(BaseChannelAdapter):
    """Bridge between python-telegram-bot and Elyan Gateway."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token")
        self.app = None
        self._is_connected = False

    async def connect(self):
        if not self.token:
            logger.error("No Telegram token provided.")
            return

        self.app = ApplicationBuilder().token(self.token).build()
        
        # Register handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self.app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        
        # Start polling
        await self.app.initialize()
        await self.app.updater.start_polling(drop_pending_updates=True)
        await self.app.start()
        
        self._is_connected = True
        logger.info("Telegram adapter connected with Voice support.")

    async def disconnect(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        self._is_connected = False

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_message or not update.effective_user:
            return

        msg = UnifiedMessage(
            id=str(update.effective_message.message_id),
            channel_type="telegram",
            channel_id=str(update.effective_chat.id),
            user_id=str(update.effective_user.id),
            user_name=update.effective_user.first_name,
            text=update.effective_message.text
        )

        if self.on_message_callback:
            await self.on_message_callback(msg)

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming voice notes."""
        if not update.message.voice: return
        
        logger.info("Receiving voice message...")
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        
        # Save temporary OGG file
        ogg_path = f"temp_{update.message.voice.file_id}.ogg"
        wav_path = f"temp_{update.message.voice.file_id}.wav"
        await voice_file.download_to_drive(ogg_path)
        
        try:
            # Convert OGG to WAV (Whisper works better with WAV)
            from pydub import AudioSegment
            audio = AudioSegment.from_ogg(ogg_path)
            audio.export(wav_path, format="wav")
            
            # Transcribe
            text = await stt_engine.transcribe(wav_path)
            
            if text:
                msg = UnifiedMessage(
                    id=str(update.message.message_id),
                    channel_type="telegram",
                    channel_id=str(update.effective_chat.id),
                    user_id=str(update.effective_user.id),
                    user_name=update.effective_user.first_name,
                    text=text,
                    metadata={"is_voice": True}
                )
                if self.on_message_callback:
                    await self.on_message_callback(msg)
            else:
                await update.message.reply_text("Sesinizi anlayamadım.")
                
        finally:
            # Cleanup
            if os.path.exists(ogg_path): os.remove(ogg_path)
            if os.path.exists(wav_path): os.remove(wav_path)

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if self.app:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=str(response.text),
                    parse_mode=None
                )
            except Exception as e:
                logger.warning(f"Telegram send failed for {chat_id}, retrying plain text: {e}")
                try:
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=str(response.text),
                        parse_mode=None,
                    )
                except Exception as inner:
                    logger.error(f"Failed to send Telegram message to {chat_id}: {inner}")

    def get_status(self) -> str:
        if not self.app:
            self._is_connected = False
            return "disconnected"

        app_running = bool(getattr(self.app, "running", False))
        updater = getattr(self.app, "updater", None)
        updater_running = bool(getattr(updater, "running", False)) if updater else False
        self._is_connected = self._is_connected and app_running and updater_running
        return "connected" if self._is_connected else "disconnected"

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "buttons": True,
            "voice": True,
            "images": True,
            "markdown": True
        }
