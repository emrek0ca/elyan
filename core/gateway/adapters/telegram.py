import asyncio
from typing import Dict, Any, List
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from tools.voice.local_stt import stt_engine
import os
from pathlib import Path
import re
from utils.logger import get_logger

logger = get_logger("telegram_adapter")

class TelegramAdapter(BaseChannelAdapter):
    """Bridge between python-telegram-bot and Elyan Gateway."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token")
        self.app = None
        self._is_connected = False
        self._image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        self._doc_exts = {
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".md",
            ".json", ".ppt", ".pptx", ".zip", ".rtf",
        }
        self._max_auto_files = max(1, min(6, int(config.get("auto_send_files_max", 3))))

    @staticmethod
    def _extract_local_image_path(text: str) -> str:
        raw = str(text or "")
        if not raw:
            return ""

        pattern = re.compile(
            r"((?:~|/)[^\n\r\t]*?\.(?:png|jpg|jpeg|webp|gif))",
            re.IGNORECASE,
        )
        for m in pattern.finditer(raw):
            candidate = str(m.group(1) or "").strip(" \t\r\n\"'`.,;:)]}")
            if not candidate:
                continue
            if "://" in candidate:
                # URL yakalanırsa dosya yolu olarak değerlendirme.
                continue
            try:
                path = Path(candidate).expanduser()
            except Exception:
                continue
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return str(path)
        return ""

    @staticmethod
    def _extract_local_paths(text: str) -> List[str]:
        raw = str(text or "")
        if not raw:
            return []

        pattern = re.compile(r"((?:~|/)[^\n\r\t]*?\.[a-z0-9]{1,8})", re.IGNORECASE)
        found: list[str] = []
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
            found.append(s)
        return found

    def _is_image_path(self, path: str) -> bool:
        try:
            return Path(path).suffix.lower() in self._image_exts
        except Exception:
            return False

    def _is_document_path(self, path: str) -> bool:
        try:
            ext = Path(path).suffix.lower()
        except Exception:
            return False
        if ext in self._image_exts:
            return False
        return ext in self._doc_exts or bool(ext)

    def _collect_local_files(self, response: UnifiedResponse, text_payload: str) -> List[str]:
        paths: list[str] = []
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
            sp = str(p)
            if sp in seen:
                continue
            seen.add(sp)
            paths.append(sp)

        for raw in self._extract_local_paths(text_payload):
            if raw in seen:
                continue
            seen.add(raw)
            paths.append(raw)

        return paths

    async def connect(self):
        if not self.token:
            logger.error("No Telegram token provided.")
            return

        # DNS Resolution Check (macOS Errno 8 mitigation)
        import socket
        try:
            socket.gethostbyname("api.telegram.org")
        except socket.gaierror as e:
            if e.errno == 8:
                logger.error("Telegram API (api.telegram.org) çözümlenemedi (DNS Hatası - Errno 8). Lütfen internet bağlantınızı veya DNS ayarlarınızı kontrol edin.")
            else:
                logger.error(f"Telegram API DNS çözümlenemedi: {e}")
            # Don't stop here, attempt connection anyway but with warning

        try:
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
        except Exception as e:
            self._is_connected = False
            logger.error(f"Telegram connection failed: {e}")
            if "nodename nor servname provided" in str(e):
                logger.warning("İpucu: DNS sorunu yaşıyor olabilirsiniz. /etc/hosts dosyanızı veya DNS sağlayıcınızı kontrol edin.")

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
            text_payload = str(getattr(response, "text", "") or "")
            paths = self._collect_local_files(response, text_payload)[: self._max_auto_files]
            image_paths = [p for p in paths if self._is_image_path(p)]
            doc_paths = [p for p in paths if self._is_document_path(p)]
            remaining_text = text_payload

            if image_paths:
                for idx, image_path in enumerate(image_paths):
                    try:
                        caption = remaining_text[:950] if remaining_text and idx == 0 else None
                        with open(image_path, "rb") as fh:
                            await self.app.bot.send_photo(
                                chat_id=chat_id,
                                photo=fh,
                                caption=caption,
                                parse_mode=None,
                            )
                        if caption:
                            remaining_text = ""
                    except Exception as photo_err:
                        logger.warning(f"Telegram image send failed for {chat_id}: {photo_err}")

            if doc_paths:
                for idx, doc_path in enumerate(doc_paths):
                    try:
                        caption = remaining_text[:950] if remaining_text and idx == 0 and not image_paths else None
                        with open(doc_path, "rb") as fh:
                            await self.app.bot.send_document(
                                chat_id=chat_id,
                                document=fh,
                                caption=caption,
                                parse_mode=None,
                            )
                        if caption:
                            remaining_text = ""
                    except Exception as doc_err:
                        logger.warning(f"Telegram document send failed for {chat_id}: {doc_err}")

            if remaining_text.strip():
                try:
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=remaining_text,
                        parse_mode=None
                    )
                except Exception as e:
                    logger.warning(f"Telegram send failed for {chat_id}, retrying plain text: {e}")
                    try:
                        await self.app.bot.send_message(
                            chat_id=chat_id,
                            text=remaining_text,
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
            "markdown": True,
            "files": True,
        }
