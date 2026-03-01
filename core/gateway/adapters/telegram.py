import asyncio
from typing import Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from .base import BaseChannelAdapter
from ..message import UnifiedMessage
from ..response import UnifiedResponse
from core.proactive.intervention import get_intervention_manager
from tools.voice.local_stt import stt_engine
import os
from pathlib import Path
import re
import time
import hashlib
from datetime import datetime
from utils.logger import get_logger
from config.settings import ELYAN_DIR

logger = get_logger("telegram_adapter")

class TelegramAdapter(BaseChannelAdapter):
    """Bridge between python-telegram-bot and Elyan Gateway."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token")
        self.app = None
        self._is_connected = False
        self._inbox_root = Path(config.get("inbox_dir") or (ELYAN_DIR / "inbox" / "telegram")).expanduser()
        self._image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        self._doc_exts = {
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".md",
            ".json", ".ppt", ".pptx", ".zip", ".rtf",
        }
        self._max_auto_files = max(1, min(6, int(config.get("auto_send_files_max", 3))))
        self._auto_send_paths_from_text = bool(config.get("auto_send_paths_from_text", False))
        self._callback_aliases: Dict[str, str] = {}
        self._max_callback_alias = max(64, int(config.get("callback_alias_cache_size", 512)))
        self._callback_stale_seconds = max(60, min(86400, int(config.get("callback_stale_seconds", 600))))

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

        if self._auto_send_paths_from_text:
            for raw in self._extract_local_paths(text_payload):
                if raw in seen:
                    continue
                seen.add(raw)
                paths.append(raw)

        return paths

    def _remember_callback_alias(self, alias: str, original: str) -> None:
        key = str(alias or "").strip()
        value = str(original or "").strip()
        if not key or not value:
            return
        self._callback_aliases[key] = value
        while len(self._callback_aliases) > self._max_callback_alias:
            try:
                first_key = next(iter(self._callback_aliases))
                self._callback_aliases.pop(first_key, None)
            except Exception:
                break

    def _compact_callback_data(self, callback_data: str) -> str:
        raw = str(callback_data or "").strip()
        if not raw:
            return ""
        if len(raw.encode("utf-8")) <= 64:
            return raw

        parsed = self._parse_intervention_callback(raw)
        if parsed:
            request_id, approved = parsed
            decision = "approve" if approved else "deny"
            alias = hashlib.sha1(request_id.encode("utf-8")).hexdigest()[:12]
            self._remember_callback_alias(alias, request_id)
            compact = f"intervention|{alias}|{decision}"
            if len(compact.encode("utf-8")) <= 64:
                return compact

        return ""

    def _resolve_callback_request_id(self, request_id: str) -> str:
        rid = str(request_id or "").strip()
        if not rid:
            return ""
        return str(self._callback_aliases.get(rid, rid))

    @staticmethod
    def _normalize_user_id(raw_user_id: Any) -> str:
        raw = str(raw_user_id or "").strip()
        if not raw:
            return ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        low = raw.lower()
        if digits and (low.isdigit() or low.startswith("telegram:") or low.startswith("tg:")):
            return digits
        return low

    @classmethod
    def _user_ids_match(cls, expected: Any, actual: Any) -> bool:
        exp = cls._normalize_user_id(expected)
        act = cls._normalize_user_id(actual)
        if not exp or not act:
            return False
        if exp == act:
            return True
        # tolerate prefixed forms (e.g., telegram:12345)
        return exp.endswith(f":{act}") or act.endswith(f":{exp}")

    def _pending_expected_user(self, pending: Dict[str, Any]) -> str:
        if not isinstance(pending, dict):
            return ""
        ctx = pending.get("context", {})
        if not isinstance(ctx, dict):
            return ""
        for key in ("telegram_user_id", "user_id", "actor_user_id"):
            val = str(ctx.get(key) or "").strip()
            if val:
                return val
        return ""

    @staticmethod
    def _pending_channel_context(pending: Dict[str, Any]) -> tuple[str, str]:
        if not isinstance(pending, dict):
            return "", ""
        ctx = pending.get("context", {})
        if not isinstance(ctx, dict):
            return "", ""
        channel = str(
            ctx.get("channel")
            or ctx.get("channel_type")
            or ""
        ).strip().lower()
        channel_id = str(
            ctx.get("channel_id")
            or ctx.get("chat_id")
            or ctx.get("target_channel_id")
            or ""
        ).strip()
        return channel, channel_id

    def _pending_matches_actor(self, pending: Dict[str, Any], actor_user: str, actor_chat: str) -> bool:
        expected_user = self._pending_expected_user(pending)
        if expected_user.lower() in {"local", "system", "0", "none", "null"}:
            expected_user = ""
        if expected_user:
            return self._user_ids_match(expected_user, actor_user)

        channel, channel_id = self._pending_channel_context(pending)
        if channel and channel not in {"telegram", "tg"}:
            return False
        if channel_id:
            return bool(actor_chat) and str(channel_id) == str(actor_chat)

        # No binding data => unsafe for fallback selection.
        return False

    def _is_pending_stale(self, pending: Dict[str, Any], now_ts: float | None = None) -> bool:
        if not isinstance(pending, dict):
            return False
        try:
            ts_val = float(pending.get("ts") or 0.0)
        except Exception:
            return False
        # Keep backward compatibility for synthetic/legacy ts values.
        if ts_val <= 1000000000:
            return False
        now = float(now_ts if now_ts is not None else time.time())
        return (now - ts_val) > float(self._callback_stale_seconds)

    def _build_reply_markup(self, buttons: List[Dict[str, Any]]) -> InlineKeyboardMarkup | None:
        if not isinstance(buttons, list) or not buttons:
            return None

        rows: Dict[int, list[InlineKeyboardButton]] = {}
        for raw in buttons:
            if not isinstance(raw, dict):
                continue

            label = str(raw.get("text") or raw.get("label") or raw.get("title") or "").strip()
            callback_data = str(raw.get("callback_data") or raw.get("value") or raw.get("id") or "").strip()
            callback_data = self._compact_callback_data(callback_data)
            if not label or not callback_data:
                continue
            # Telegram callback_data limit: 64 bytes.
            if len(callback_data.encode("utf-8")) > 64:
                logger.warning(f"Skipping oversized callback_data ({len(callback_data)} chars): {label}")
                continue

            try:
                row_idx = int(raw.get("row", 0))
            except Exception:
                row_idx = 0
            rows.setdefault(row_idx, []).append(
                InlineKeyboardButton(text=label, callback_data=callback_data)
            )

        keyboard = [rows[idx] for idx in sorted(rows) if rows[idx]]
        return InlineKeyboardMarkup(keyboard) if keyboard else None

    @staticmethod
    def _parse_intervention_callback(data: str) -> tuple[str, bool] | None:
        raw = str(data or "").strip()
        if not raw:
            return None

        def _decision_value(token: str) -> bool | None:
            t = str(token or "").strip().lower()
            if not t:
                return None
            t = re.split(r"[:|]", t, maxsplit=1)[0].strip()
            t_norm = (
                t.replace(" ", "")
                .replace("_", "")
                .replace("-", "")
                .replace("ı", "i")
                .replace("İ", "i")
            )
            approve_tokens = {"approve", "onayla", "onay", "yes", "true", "1", "ok", "tamam"}
            deny_tokens = {"deny", "reject", "reddet", "iptal", "iptalet", "cancel", "no", "false", "0"}
            if t_norm in approve_tokens:
                return True
            if t_norm in deny_tokens:
                return False
            return None

        # 1) Standard forms:
        # intervention:req123:approve
        # intervention|req123|approve
        # INTERVENTION:req123:approve:v2
        match = re.match(r"(?i)^intervention[:|]([^:|]+)[:|](.+)$", raw)
        if match:
            req = str(match.group(1) or "").strip()
            dec = _decision_value(str(match.group(2) or ""))
            if req and dec is not None:
                return req, dec

            # Support swapped payloads:
            # intervention:approve:req123
            # intervention|deny|req123
            maybe_dec = _decision_value(str(match.group(1) or ""))
            maybe_req = str(match.group(2) or "").strip()
            maybe_req = re.split(r"[:|]", maybe_req, maxsplit=1)[0].strip()
            if maybe_req and maybe_dec is not None:
                return maybe_req, maybe_dec

        # 2) Legacy short forms without "intervention" prefix:
        # approve:req123 / deny|req123 / onayla:req123 / iptal:req123
        match2 = re.match(r"(?i)^([a-zA-Zçğıöşüİı_ -]+)[:|]([^:|]+)$", raw)
        if match2:
            left = str(match2.group(1) or "").strip()
            right = str(match2.group(2) or "").strip()
            left_dec = _decision_value(left)
            if left_dec is not None and right:
                return right, left_dec
            right_dec = _decision_value(right)
            if right_dec is not None and left:
                return left, right_dec

        return None

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
            self.app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
            self.app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
            self.app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
            # Button/callback approval flow disabled (text-only interaction).
            
            # Start polling
            await self.app.initialize()
            await self.app.updater.start_polling(drop_pending_updates=True)
            await self.app.start()
            
            self._is_connected = True
            from ..monitoring import adapter_monitor
            adapter_monitor.record_heartbeat("telegram")
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

        text = update.effective_message.text or ""

        # Command handling
        if text.startswith("/"):
            await self._handle_command(update, context)
            return

        from ..monitoring import adapter_monitor
        adapter_monitor.record_heartbeat("telegram")

        msg = UnifiedMessage(
            id=str(update.effective_message.message_id),
            channel_type="telegram",
            channel_id=str(update.effective_chat.id),
            user_id=str(update.effective_user.id),
            user_name=update.effective_user.first_name,
            text=text
        )

        if self.on_message_callback:
            await self.on_message_callback(msg)

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Modular command handler."""
        text = update.effective_message.text or ""
        command = text.split()[0].lower()
        
        if command == "/start":
            await update.message.reply_text("Elyan Sistemine Hoş Geldiniz. Ben sizin dijital operasyon asistanınızım.")
        elif command == "/status":
            from ..monitoring import adapter_monitor
            report = adapter_monitor.get_status_report()
            status = report.get("telegram", {}).get("status", "unknown")
            await update.message.reply_text(f"Sistem Durumu: Çevrimiçi\nTelegram Adaptörü: {status.upper()}")
        else:
            await update.message.reply_text("Bilinmeyen komut.")

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

    def _resolve_inbox_dir(self, user_id: str) -> Path:
        day = datetime.now().strftime("%Y-%m-%d")
        target = self._inbox_root / str(user_id or "unknown") / day
        target.mkdir(parents=True, exist_ok=True)
        return target

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = getattr(update, "effective_message", None)
        user = getattr(update, "effective_user", None)
        if not msg or not user or not getattr(msg, "photo", None):
            return

        try:
            photo = msg.photo[-1]
            file_obj = await context.bot.get_file(photo.file_id)
            inbox_dir = self._resolve_inbox_dir(str(user.id))
            ext = ".jpg"
            dest = inbox_dir / f"photo_{msg.message_id}{ext}"
            await file_obj.download_to_drive(str(dest))

            text = (msg.caption or "").strip() or "Fotoğraf eklendi."
            unified = UnifiedMessage(
                id=str(msg.message_id),
                channel_type="telegram",
                channel_id=str(update.effective_chat.id),
                user_id=str(user.id),
                user_name=user.first_name,
                text=text,
                attachments=[
                    {
                        "path": str(dest),
                        "type": "image",
                        "mime": "image/jpeg",
                        "name": dest.name,
                        "source": "telegram",
                    }
                ],
                metadata={"attachment_type": "photo"},
            )
            if self.on_message_callback:
                await self.on_message_callback(unified)
        except Exception as exc:
            logger.error(f"Telegram photo ingest failed: {exc}")

    async def _handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = getattr(update, "effective_message", None)
        user = getattr(update, "effective_user", None)
        document = getattr(msg, "document", None) if msg else None
        if not msg or not user or not document:
            return

        try:
            file_obj = await context.bot.get_file(document.file_id)
            inbox_dir = self._resolve_inbox_dir(str(user.id))
            original_name = str(document.file_name or f"document_{msg.message_id}").strip() or f"document_{msg.message_id}"
            safe_name = Path(original_name).name
            dest = inbox_dir / f"{msg.message_id}_{safe_name}"
            await file_obj.download_to_drive(str(dest))

            text = (msg.caption or "").strip() or f"Dosya eklendi: {safe_name}"
            unified = UnifiedMessage(
                id=str(msg.message_id),
                channel_type="telegram",
                channel_id=str(update.effective_chat.id),
                user_id=str(user.id),
                user_name=user.first_name,
                text=text,
                attachments=[
                    {
                        "path": str(dest),
                        "type": "document",
                        "mime": str(document.mime_type or ""),
                        "name": safe_name,
                        "size_bytes": int(document.file_size or 0),
                        "source": "telegram",
                    }
                ],
                metadata={"attachment_type": "document"},
            )
            if self.on_message_callback:
                await self.on_message_callback(unified)
        except Exception as exc:
            logger.error(f"Telegram document ingest failed: {exc}")

    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = getattr(update, "callback_query", None)
        user = getattr(update, "effective_user", None) or getattr(query, "from_user", None)
        if not query or not user:
            return

        data = str(getattr(query, "data", "") or "")
        parsed = self._parse_intervention_callback(data)
        if not parsed:
            try:
                await query.answer("Geçersiz onay verisi.", show_alert=True)
            except Exception:
                pass
            return
        request_id, approved = parsed
        request_id = self._resolve_callback_request_id(request_id)
        decision = "Onayla" if approved else "İptal Et"
        try:
            await query.answer()
        except Exception:
            pass

        logger.info(
            f"Intervention callback received: request_id={request_id} decision={decision} "
            f"user={getattr(user, 'id', '?')}"
        )
        manager = get_intervention_manager()
        pending = None
        actor_user = str(getattr(user, "id", "") or "").strip()
        actor_chat = ""
        try:
            if getattr(query, "message", None) and getattr(query.message, "chat", None):
                actor_chat = str(query.message.chat.id)
            elif getattr(update, "effective_chat", None):
                actor_chat = str(update.effective_chat.id)
        except Exception:
            actor_chat = ""
        pending_list_raw = manager.list_pending()
        pending_list = [req for req in pending_list_raw if isinstance(req, dict)]
        now_ts = time.time()

        matched_by_id: Dict[str, Any] | None = None
        for req in pending_list:
            if str(req.get("id") or "") == str(request_id):
                matched_by_id = req
                break
        if matched_by_id is not None:
            expected_user = self._pending_expected_user(matched_by_id)
            if expected_user.lower() in {"local", "system", "0", "none", "null"}:
                expected_user = ""
            if expected_user and actor_user and not self._user_ids_match(expected_user, actor_user):
                try:
                    await query.answer("Bu onay isteği size ait değil.", show_alert=True)
                except Exception:
                    pass
                return
            if not expected_user:
                req_channel, req_channel_id = self._pending_channel_context(matched_by_id)
                if req_channel and req_channel not in {"telegram", "tg"}:
                    try:
                        await query.answer("Bu onay isteği bu kanala ait değil.", show_alert=True)
                    except Exception:
                        pass
                    return
                if req_channel_id and actor_chat and str(req_channel_id) != str(actor_chat):
                    try:
                        await query.answer("Bu onay isteği bu sohbete ait değil.", show_alert=True)
                    except Exception:
                        pass
                    return
            if self._is_pending_stale(matched_by_id, now_ts):
                status_text = "Bu onay isteğinin süresi dolmuş. Komutu tekrar gönder."
                try:
                    await query.answer(status_text, show_alert=True)
                except Exception:
                    pass
                try:
                    await query.edit_message_text(status_text, parse_mode=None)
                except Exception:
                    pass
                return
            pending = matched_by_id

        if pending is None and actor_user:
            # Fallback: callback id eşleşmezse kullanıcıya ait en güncel, süresi geçmemiş pending istek.
            candidates: list[Dict[str, Any]] = []
            for req in pending_list:
                if not self._pending_matches_actor(req, actor_user, actor_chat):
                    continue
                if self._is_pending_stale(req, now_ts):
                    continue
                candidates.append(req)
            if candidates:
                candidates.sort(key=lambda req: float(req.get("ts") or 0.0), reverse=True)
                pending = candidates[0]

        target_request_id = str(request_id or "").strip()
        if isinstance(pending, dict) and str(pending.get("id") or "").strip():
            target_request_id = str(pending.get("id") or "").strip()
        pending_ids = {str(req.get("id") or "").strip() for req in pending_list if isinstance(req, dict)}
        if target_request_id and target_request_id in pending_ids:
            resolved = manager.resolve(target_request_id, decision)
        else:
            resolved = False
        logger.info(
            f"Intervention callback resolved: request_id={request_id} target={target_request_id} "
            f"resolved={resolved} pending_count={len(pending_list)}"
        )
        status_text = "Onay alındı. İşlem devam ediyor." if approved else "İşlem reddedildi."
        if not resolved:
            status_text = "Bu onay isteği artık geçerli değil. Komutu yeniden çalıştırıp tekrar deneyin."

        try:
            await query.edit_message_text(status_text, parse_mode=None)
        except Exception:
            try:
                chat_id = ""
                if getattr(query, "message", None) and getattr(query.message, "chat", None):
                    chat_id = str(query.message.chat.id)
                elif getattr(update, "effective_chat", None):
                    chat_id = str(update.effective_chat.id)
                elif actor_user:
                    chat_id = str(actor_user)
                if not chat_id:
                    return
                await self.app.bot.send_message(chat_id=chat_id, text=status_text, parse_mode=None)
            except Exception:
                pass

    async def send_message(self, chat_id: str, response: UnifiedResponse):
        if not self.app:
            raise RuntimeError("Telegram app başlatılmamış")

        text_payload = str(getattr(response, "text", "") or "")
        # Disable Telegram inline buttons globally; keep interaction text-only.
        reply_markup = None
        paths = self._collect_local_files(response, text_payload)[: self._max_auto_files]
        image_paths = [p for p in paths if self._is_image_path(p)]
        doc_paths = [p for p in paths if self._is_document_path(p)]
        remaining_text = text_payload
        delivered = False
        last_error: Exception | None = None

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
                    delivered = True
                    if caption:
                        remaining_text = ""
                except Exception as photo_err:
                    last_error = photo_err
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
                    delivered = True
                    if caption:
                        remaining_text = ""
                except Exception as doc_err:
                    last_error = doc_err
                    logger.warning(f"Telegram document send failed for {chat_id}: {doc_err}")

        if remaining_text.strip():
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=remaining_text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                )
                delivered = True
            except Exception as e:
                last_error = e
                logger.warning(f"Telegram send failed for {chat_id}, retrying plain text: {e}")
                try:
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=remaining_text,
                        parse_mode=None,
                    )
                    delivered = True
                except Exception as inner:
                    last_error = inner
                    logger.error(f"Failed to send Telegram message to {chat_id}: {inner}")
        elif reply_markup is not None:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text="Lütfen seçim yapın.",
                    parse_mode=None,
                    reply_markup=reply_markup,
                )
                delivered = True
            except Exception as inner:
                last_error = inner
                logger.error(f"Failed to send Telegram button message to {chat_id}: {inner}")

        if not delivered:
            if last_error:
                raise last_error
            raise RuntimeError("Telegram message deliver edilemedi")

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
