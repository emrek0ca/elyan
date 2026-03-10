import asyncio
import inspect
import json
import re
import secrets
import time
from pathlib import Path
from typing import Dict, Any, Optional
from .message import UnifiedMessage
from .response import ChannelEnvelope, UnifiedResponse
from .adapters.base import BaseChannelAdapter
from core.multi_agent.router import agent_router
from core.proactive.intervention import get_intervention_manager
from .channel_capabilities import resolve_channel_capabilities
from core.channel_delivery import channel_delivery_bridge
from config.settings import ELYAN_DIR
from utils.logger import get_logger

logger = get_logger("gateway_router")

class GatewayRouter:
    """Orchestrates message flow between adapters and the AI Agent pool."""
    
    def __init__(self, agent=None, *, welcome_enabled: bool = True, welcome_state_path: Optional[str] = None):
        self.default_agent = agent # Kept for backward compatibility
        self.adapters: Dict[str, BaseChannelAdapter] = {}
        self._is_running = False
        self._supervisor_tasks: Dict[str, asyncio.Task] = {}
        self._adapter_health: Dict[str, Dict[str, Any]] = {}
        self._user_routes: Dict[str, Dict[str, str]] = {}
        self._intervention_manager = None
        self._approval_codes: Dict[str, Dict[str, Any]] = {}
        self._approval_code_ttl_s = 300
        self._welcome_enabled = bool(welcome_enabled)
        self._welcome_channels = {"telegram", "whatsapp"}
        self._welcome_lock = asyncio.Lock()
        self._welcomed_users: set[str] = set()
        if welcome_state_path:
            self._welcome_state_path = Path(str(welcome_state_path)).expanduser()
        else:
            self._welcome_state_path = ELYAN_DIR / "welcome_state.json"
        self._load_welcome_state()
        try:
            self._intervention_manager = get_intervention_manager()
            self._intervention_manager.register_listener(self._on_intervention_requested)
        except Exception as exc:
            logger.debug(f"Intervention listener registration failed: {exc}")
        channel_delivery_bridge.register_sender(self.send_outgoing_response)

    @staticmethod
    def _channel_text_limit(channel_type: str) -> int:
        caps = resolve_channel_capabilities(channel_type, {})
        try:
            return max(300, int(caps.get("text_limit", 3500)))
        except Exception:
            return 3500

    @classmethod
    def _truncate_text_for_channel(cls, text: str, channel_type: str) -> str:
        raw = str(text or "")
        if not raw.strip():
            return ""
        limit = cls._channel_text_limit(channel_type)
        if len(raw) <= limit:
            return raw
        suffix = "\n\n[Mesaj kanal sınırı nedeniyle kısaltıldı]"
        keep = max(0, limit - len(suffix))
        return raw[:keep].rstrip() + suffix

    @classmethod
    def _build_task_inbox_buttons(cls, response: UnifiedResponse) -> list[dict[str, Any]]:
        if list(getattr(response, "buttons", []) or []):
            return list(getattr(response, "buttons", []) or [])
        meta = dict(getattr(response, "metadata", {}) or {})
        buttons: list[dict[str, Any]] = []
        task = meta.get("task") if isinstance(meta.get("task"), dict) else None
        task_list = meta.get("task_list") if isinstance(meta.get("task_list"), list) else []
        recent_tasks = meta.get("recent_tasks") if isinstance(meta.get("recent_tasks"), list) else []
        task_suggestion = meta.get("task_suggestion") if isinstance(meta.get("task_suggestion"), dict) else None

        def _task_id(item: dict[str, Any]) -> str:
            return str(item.get("task_id") or "").strip()

        def _task_state(item: dict[str, Any]) -> str:
            return str(item.get("state") or "").strip().lower()

        if task:
            task_id = _task_id(task)
            state = _task_state(task)
            if task_id:
                buttons.append({"text": "Durum", "callback_data": f"task|status|{task_id}", "row": 0})
                if state in {"queued", "running", "partial"}:
                    buttons.append({"text": "Iptal", "callback_data": f"task|cancel|{task_id}", "row": 0})
                if state in {"failed", "cancelled", "partial", "completed"}:
                    buttons.append({"text": "Yeniden Baslat", "callback_data": f"task|retry|{task_id}", "row": 1})
                return buttons

        if task_suggestion:
            task_id = _task_id(task_suggestion)
            suggested_action = str(task_suggestion.get("suggested_action") or "status").strip().lower()
            if task_id:
                if suggested_action == "retry":
                    buttons.append({"text": "Devam Et", "callback_data": f"task|retry|{task_id}", "row": 0})
                else:
                    buttons.append({"text": "Durum", "callback_data": f"task|status|{task_id}", "row": 0})
                buttons.append({"text": "Detay", "callback_data": f"task|status|{task_id}", "row": 1})
                return buttons

        candidate_list = task_list or recent_tasks
        if candidate_list:
            first = candidate_list[0] if isinstance(candidate_list[0], dict) else None
            if first:
                task_id = _task_id(first)
                state = _task_state(first)
                if task_id:
                    buttons.append({"text": "Ilk Gorev Durumu", "callback_data": f"task|status|{task_id}", "row": 0})
                    if state in {"queued", "running", "partial"}:
                        buttons.append({"text": "Ilk Gorevi Iptal", "callback_data": f"task|cancel|{task_id}", "row": 1})
            buttons.append({"text": "Yenile", "callback_data": "task|list", "row": 2})
        return buttons

    @classmethod
    def _normalize_response_for_channel(
        cls,
        channel_type: str,
        response: UnifiedResponse,
        adapter: BaseChannelAdapter,
    ) -> UnifiedResponse:
        caps = {}
        try:
            caps_raw = adapter.get_capabilities()
            if isinstance(caps_raw, dict):
                caps = caps_raw
        except Exception:
            caps = {}

        resolved_caps = resolve_channel_capabilities(channel_type, caps)
        supports_markdown = bool(resolved_caps.get("markdown") or resolved_caps.get("html"))
        supports_buttons = bool(resolved_caps.get("buttons"))
        supports_images = bool(resolved_caps.get("images"))
        supports_files = bool(resolved_caps.get("files"))

        envelope = response.to_channel_envelope() if hasattr(response, "to_channel_envelope") else ChannelEnvelope(text=str(getattr(response, "text", "") or ""))
        text = cls._truncate_text_for_channel(str(envelope.text or ""), channel_type)
        if not text.strip():
            text = "İşlem tamamlandı."

        images = list(envelope.images or [])
        files = list(envelope.files or [])
        fallback_lines: list[str] = []

        if images and not supports_images:
            fallback_lines.append("Gorseller:")
            fallback_lines.extend(f"- {str(item.get('name') or item.get('path') or 'gorsel')}" for item in images[:4])
            images = []
        if files and not supports_files:
            fallback_lines.append("Dosyalar:")
            fallback_lines.extend(f"- {str(item.get('name') or item.get('path') or 'dosya')}" for item in files[:4])
            files = []

        attachments = [*images[:4], *files[:4]]
        fallback_text = str(envelope.fallback_text or "").strip()
        if fallback_lines:
            extra = "\n".join(fallback_lines)
            fallback_text = f"{fallback_text}\n{extra}".strip() if fallback_text else extra

        if attachments and len(text) > 700:
            text = text[:660].rstrip() + "\n\n[Ekler gönderildi]"
        elif fallback_text:
            combined = f"{text}\n\n{fallback_text}".strip()
            text = cls._truncate_text_for_channel(combined, channel_type)

        task_buttons = cls._build_task_inbox_buttons(response) if supports_buttons else []
        normalized = UnifiedResponse(
            text=text,
            attachments=attachments,
            buttons=(list(envelope.buttons or []) if supports_buttons else []) or task_buttons,
            format=str(envelope.format or "plain"),
            metadata=dict(envelope.metadata or {}),
            channel_hints=dict(envelope.channel_hints or {}),
        )
        if fallback_text:
            normalized.metadata["fallback_text"] = fallback_text
        if not supports_markdown and normalized.format != "plain":
            normalized.format = "plain"
        return normalized

    @classmethod
    def _build_plain_fallback_response(cls, channel_type: str, response: UnifiedResponse) -> UnifiedResponse:
        text = cls._truncate_text_for_channel(str(getattr(response, "text", "") or ""), channel_type)
        if not text.strip():
            text = "Üzgünüm, yanıtı iletirken bir hata oluştu. Lütfen tekrar deneyin."
        return UnifiedResponse(text=text, format="plain")

    @classmethod
    def _build_short_plain_fallback_response(cls, channel_type: str, response: UnifiedResponse) -> UnifiedResponse:
        text = cls._truncate_text_for_channel(str(getattr(response, "text", "") or ""), channel_type)
        text = (text or "").strip()
        if len(text) > 900:
            text = text[:860].rstrip() + "\n\n[Mesaj kısaltıldı]"
        if not text:
            text = "İşlem alındı. Yanıt gönderiminde sorun oluştu, tekrar dener misin?"
        return UnifiedResponse(text=text, format="plain")

    @staticmethod
    def _normalize_inbound_attachments(raw_attachments: Any) -> list[Dict[str, Any]]:
        normalized: list[Dict[str, Any]] = []
        seen: set[str] = set()
        items = raw_attachments if isinstance(raw_attachments, list) else []
        for item in items:
            if isinstance(item, str):
                path = str(item).strip()
                if not path or path in seen:
                    continue
                seen.add(path)
                normalized.append({"path": path, "type": "file", "source": "channel"})
                continue
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("file_path") or item.get("local_path") or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            atype = str(item.get("type") or "").strip().lower()
            if not atype:
                mime = str(item.get("mime") or "").lower()
                if mime.startswith("image/"):
                    atype = "image"
                else:
                    atype = "file"
            normalized.append(
                {
                    "path": path,
                    "type": atype,
                    "mime": str(item.get("mime") or "").strip(),
                    "name": str(item.get("name") or "").strip(),
                    "source": str(item.get("source") or "channel"),
                }
            )
        return normalized

    def register_adapter(self, channel_type: str, adapter: BaseChannelAdapter):
        """Register a new channel adapter."""
        self.adapters[channel_type] = adapter
        adapter.on_message(self.handle_incoming_message)
        self._adapter_health[channel_type] = {
            "channel": channel_type,
            "status": "registered",
            "connected": False,
            "retries": 0,
            "failures": 0,
            "last_error": None,
            "last_attempt_ts": None,
            "last_connected_ts": None,
            "next_retry_in_s": 0.0,
            "received_count": 0,
            "sent_count": 0,
            "send_failures": 0,
            "processing_errors": 0,
            "last_message_in_ts": None,
            "last_message_out_ts": None,
        }
        logger.info(f"Adapter registered: {channel_type}")

    async def handle_incoming_message(self, message: UnifiedMessage):
        """Callback triggered by any adapter when a message is received."""
        message.attachments = self._normalize_inbound_attachments(getattr(message, "attachments", []))
        logger.info(f"Incoming: [{message.channel_type}] user={message.user_id} text={message.text[:50]}")
        self._remember_user_route(message)
        self._mark_incoming_message(message.channel_type)
        await self._maybe_send_first_contact_welcome(message)

        if await self._handle_intervention_message(message):
            return

        try:
            agent = await agent_router.route_message(message.channel_type, message.user_id)
            agent.current_user_id = message.user_id

            # Notify dashboard
            try:
                from core.gateway.server import push_activity
                push_activity("message", message.channel_type, message.text[:60])
            except Exception:
                pass

            # ── Specialist Detection & Typing Indicator ──
            try:
                from core.multi_agent.specialists import get_specialist_registry
                specialist = get_specialist_registry().select_for_input(message.text)
                specialist_tag = f"{specialist.emoji} {specialist.name}" if specialist else ""
            except Exception:
                specialist_tag = ""

            # Send typing/processing indicator
            typing_text = f"⏳ Çalışıyorum..." + (f" ({specialist_tag})" if specialist_tag else "")
            try:
                await self._send_typing_indicator(message.channel_type, message.channel_id, typing_text)
            except Exception:
                pass

            # ── Notify callback for step-by-step progress ──
            async def _notify_progress(status_msg: str):
                try:
                    progress_resp = UnifiedResponse(text=status_msg, format="plain")
                    await self.send_outgoing_response(
                        message.channel_type, message.channel_id, progress_resp
                    )
                except Exception:
                    pass

            agent_meta: Dict[str, Any] = {}
            if isinstance(message.metadata, dict):
                agent_meta.update(message.metadata)
            agent_meta.setdefault("channel_type", str(getattr(message, "channel_type", "") or ""))
            agent_meta.setdefault("channel_id", str(getattr(message, "channel_id", "") or ""))
            agent_meta.setdefault("user_id", str(getattr(message, "user_id", "") or ""))
            # Secure-by-default metadata:
            # - no implicit full autonomy
            # - interactive approval must be explicitly available per channel
            channel_type_norm = str(getattr(message, "channel_type", "") or "").strip().lower()
            agent_meta.setdefault("interactive_approval", channel_type_norm == "telegram")
            agent_meta.setdefault("autonomy_mode", "balanced")

            response = None
            envelope_handler = None
            try:
                has_instance_method = "process_envelope" in getattr(agent, "__dict__", {})
                has_class_method = callable(getattr(type(agent), "process_envelope", None))
                if has_instance_method or has_class_method:
                    envelope_handler = getattr(agent, "process_envelope", None)
            except Exception:
                envelope_handler = None

            if callable(envelope_handler):
                envelope = await agent.process_envelope(
                    message.text,
                    notify=_notify_progress,
                    attachments=list(getattr(message, "attachments", []) or []),
                    channel=message.channel_type,
                    metadata=agent_meta,
                )
                text = str(getattr(envelope, "text", "") or "")
                attachments = []
                if hasattr(envelope, "to_unified_attachments"):
                    try:
                        converted = envelope.to_unified_attachments()
                        if inspect.isawaitable(converted):
                            converted = await converted
                        attachments = list(converted or [])
                    except Exception:
                        attachments = []
                if not attachments and hasattr(envelope, "attachments"):
                    raw_attachments = list(getattr(envelope, "attachments", []) or [])
                    attachments = [a.to_dict() if hasattr(a, "to_dict") else a for a in raw_attachments if isinstance(a, (dict, object))]

                manifest = str(getattr(envelope, "evidence_manifest_path", "") or "").strip()
                if manifest:
                    attachments.append({"path": manifest, "type": "manifest"})
                response = UnifiedResponse(
                    text=text,
                    format="markdown",
                    attachments=[a for a in attachments if isinstance(a, dict)],
                    metadata={
                        "run_id": getattr(envelope, "run_id", ""),
                        "status": getattr(envelope, "status", "success"),
                        **(dict(getattr(envelope, "metadata", {}) or {})),
                    },
                )
            else:
                response_text = await agent.process(
                    message.text,
                    notify=_notify_progress,
                    attachments=list(getattr(message, "attachments", []) or []),
                    channel=message.channel_type,
                    metadata=agent_meta,
                )
                response = UnifiedResponse(text=response_text, format="markdown")
            await self.send_outgoing_response(message.channel_type, message.channel_id, response)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            self._increment_counter(message.channel_type, "processing_errors")
            try:
                from core.gateway.server import push_activity
                push_activity("error", message.channel_type, str(e)[:60], success=False)
            except Exception:
                pass
            error_resp = UnifiedResponse(text="Üzgünüm, bu isteği işlerken bir hata oluştu. Tekrar dener misin?")
            await self.send_outgoing_response(message.channel_type, message.channel_id, error_resp)

    def _remember_user_route(self, message: UnifiedMessage) -> None:
        user_id = str(getattr(message, "user_id", "") or "").strip()
        if not user_id:
            return
        self._user_routes[user_id] = {
            "channel_type": str(getattr(message, "channel_type", "") or "").strip(),
            "channel_id": str(getattr(message, "channel_id", "") or "").strip(),
        }

    @staticmethod
    def _parse_intervention_decision(text: str) -> Optional[str]:
        raw = str(text or "").strip().lower()
        if not raw:
            return None
        raw = raw.lstrip("/")
        tokens = set(re.findall(r"[0-9a-zçğıöşü]+", raw, flags=re.IGNORECASE))

        approve_tokens = {
            "onay", "onayla", "evet", "yes", "approve", "approved", "tamam", "ok",
        }
        deny_tokens = {
            "iptal", "reddet", "hayir", "hayır", "no", "deny", "cancel", "vazgec", "vazgeç",
        }

        if raw in approve_tokens or tokens.intersection(approve_tokens):
            return "Onayla"
        if raw in deny_tokens or tokens.intersection(deny_tokens):
            return "İptal Et"
        return None

    @staticmethod
    def _extract_approval_code(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        # Accept plain code-only message or phrases like "onay K9P3X2" / "kod: K9P3X2".
        m = re.search(r"\b([A-Za-z0-9]{4,12})\b", raw)
        if m and raw.replace(m.group(1), "").strip() == "":
            return str(m.group(1)).upper()

        patterns = [
            r"(?i)\b(?:onay|approve|code|kod)\b[\s:=-]*([A-Za-z0-9]{4,12})\b",
            r"(?i)\b([A-Za-z0-9]{4,12})\b[\s:=-]*\b(?:onay|approve)\b",
        ]
        for pat in patterns:
            mm = re.search(pat, raw)
            if mm:
                return str(mm.group(1)).upper()
        return ""

    @staticmethod
    def _new_security_code(length: int = 6) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        size = max(4, min(10, int(length or 6)))
        return "".join(secrets.choice(alphabet) for _ in range(size))

    def _ensure_intervention_code(self, req: Dict[str, Any], *, user_id: str = "", channel_id: str = "") -> str:
        req_id = str((req or {}).get("id") or "").strip()
        if not req_id:
            return ""
        now = time.time()
        current = self._approval_codes.get(req_id)
        if isinstance(current, dict):
            exp = float(current.get("expires_at") or 0.0)
            if exp > now:
                return str(current.get("code") or "")
        code = self._new_security_code(6)
        self._approval_codes[req_id] = {
            "code": code,
            "expires_at": now + float(self._approval_code_ttl_s),
            "user_id": str(user_id or ""),
            "channel_id": str(channel_id or ""),
            "issued_at": now,
        }
        return code

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
        return exp.endswith(f":{act}") or act.endswith(f":{exp}")

    @staticmethod
    def _is_intervention_stale(req: Dict[str, Any], now_ts: float | None = None) -> bool:
        if not isinstance(req, dict):
            return False
        try:
            ts = float(req.get("ts") or 0.0)
        except Exception:
            return False
        # Backward compatibility for synthetic/legacy timestamps in tests/mocks.
        if ts <= 1000000000:
            return False
        now = float(now_ts if now_ts is not None else time.time())
        return (now - ts) > 600.0

    @staticmethod
    def _intervention_channel_context(req: Dict[str, Any]) -> tuple[str, str]:
        if not isinstance(req, dict):
            return "", ""
        context = req.get("context", {})
        if not isinstance(context, dict):
            return "", ""
        channel = str(context.get("channel") or context.get("channel_type") or "").strip().lower()
        channel_id = str(
            context.get("channel_id")
            or context.get("chat_id")
            or context.get("target_channel_id")
            or ""
        ).strip()
        return channel, channel_id

    @staticmethod
    def _intervention_buttons(request_id: str) -> list[Dict[str, Any]]:
        # Button-based approval flow is intentionally disabled.
        return []

    @staticmethod
    def _find_intervention_for_user(
        user_id: str,
        request_id: str = "",
        *,
        channel_type: str = "",
        channel_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        manager = get_intervention_manager()
        pending = manager.list_pending()
        if not pending:
            return None

        uid = str(user_id or "").strip()
        req_id = str(request_id or "").strip()
        in_channel = str(channel_type or "").strip().lower()
        in_channel_id = str(channel_id or "").strip()
        selected: Optional[Dict[str, Any]] = None
        latest_ts = float("-inf")
        now_ts = time.time()

        for req in pending:
            if not isinstance(req, dict):
                continue
            if GatewayRouter._is_intervention_stale(req, now_ts):
                continue
            context = req.get("context", {})
            req_uid = str(context.get("user_id") or "").strip() if isinstance(context, dict) else ""
            if req_uid and not GatewayRouter._user_ids_match(req_uid, uid):
                continue
            if not req_uid:
                req_channel, req_channel_id = GatewayRouter._intervention_channel_context(req)
                if req_channel and in_channel and req_channel != in_channel:
                    continue
                if req_channel_id and in_channel_id and req_channel_id != in_channel_id:
                    continue
                # No user and no channel binding => only safe for explicit request id.
                if not req_id and not req_channel_id:
                    continue
            if req_id and str(req.get("id") or "").strip() == req_id:
                return req
            ts = float(req.get("ts") or 0.0)
            if ts >= latest_ts:
                selected = req
                latest_ts = ts
        return selected

    def _build_intervention_response(self, channel_type: str, req: Dict[str, Any], *, user_id: str = "", channel_id: str = "") -> UnifiedResponse:
        prompt = str(req.get("prompt") or "Bekleyen bir onay isteği var.").strip()
        code = self._ensure_intervention_code(req, user_id=user_id, channel_id=channel_id)
        text = (
            f"{prompt}\n\n"
            "Kritik işlem onayı için güvenlik kodu gerekiyor.\n"
            f"Kod: `{code}`\n"
            "Onaylamak için kodu yaz: `ONAY <KOD>` (örn: `ONAY "
            f"{code}`)\n"
            "İptal için: `İPTAL`"
        )
        return UnifiedResponse(text=text, format="plain", buttons=[])

    async def _handle_intervention_message(self, message: UnifiedMessage) -> bool:
        """Resolve pending intervention requests from channel replies."""
        user_id = str(getattr(message, "user_id", "") or "").strip()
        if not user_id:
            return False

        meta = message.metadata if isinstance(getattr(message, "metadata", None), dict) else {}
        req_id = str(meta.get("intervention_id") or "").strip()
        pending = self._find_intervention_for_user(
            user_id,
            request_id=req_id,
            channel_type=str(getattr(message, "channel_type", "") or ""),
            channel_id=str(getattr(message, "channel_id", "") or ""),
        )
        if not pending:
            return False

        target_id = str(pending.get("id") or "").strip()
        if not target_id:
            return False

        decision = str(meta.get("intervention_decision") or "").strip()
        provided_code = str(meta.get("approval_code") or "").strip().upper()
        if not provided_code:
            provided_code = self._extract_approval_code(message.text)
        if decision not in {"Onayla", "İptal Et"}:
            decision = self._parse_intervention_decision(message.text) or ""
        if not decision and provided_code:
            decision = "Onayla"
        if not decision:
            await self.send_outgoing_response(
                message.channel_type,
                message.channel_id,
                self._build_intervention_response(
                    message.channel_type,
                    pending,
                    user_id=user_id,
                    channel_id=str(getattr(message, "channel_id", "") or ""),
                ),
            )
            return True

        if decision == "Onayla":
            expected = self._ensure_intervention_code(
                pending,
                user_id=user_id,
                channel_id=str(getattr(message, "channel_id", "") or ""),
            )
            if not provided_code or provided_code != str(expected or "").upper():
                await self.send_outgoing_response(
                    message.channel_type,
                    message.channel_id,
                    UnifiedResponse(
                        text=(
                            "Onay kodu doğrulanamadı.\n"
                            f"Lütfen şu formatı kullan: `ONAY {expected}`\n"
                            "İptal için: `İPTAL`"
                        ),
                        format="plain",
                    ),
                )
                return True

        manager = get_intervention_manager()
        resolved = manager.resolve(target_id, decision)
        if not resolved:
            return False
        self._approval_codes.pop(target_id, None)

        ack = "Onay alındı. İşlem devam ediyor." if decision == "Onayla" else "İşlem iptal edildi."
        await self.send_outgoing_response(
            message.channel_type,
            message.channel_id,
            UnifiedResponse(text=ack, format="plain"),
        )
        return True

    async def _on_intervention_requested(self, request: Any) -> None:
        """Bridge intervention prompts to the last active user channel."""
        context = getattr(request, "context", {})
        if not isinstance(context, dict):
            return
        user_id = str(context.get("user_id") or "").strip()
        if not user_id:
            return

        route = self._user_routes.get(user_id)
        if not route:
            logger.warning(f"Intervention routing missing for user={user_id} request={getattr(request, 'id', '?')}")
            return

        options = getattr(request, "options", None) or []
        req_payload = {
            "id": str(getattr(request, "id", "") or ""),
            "prompt": str(getattr(request, "prompt", "") or ""),
            "options": options,
        }
        try:
            await self.send_outgoing_response(
                route.get("channel_type", ""),
                route.get("channel_id", ""),
                self._build_intervention_response(
                    route.get("channel_type", ""),
                    req_payload,
                    user_id=user_id,
                    channel_id=route.get("channel_id", ""),
                ),
            )
        except Exception as exc:
            logger.warning(f"Failed to deliver intervention request to channel: {exc}")

    async def _send_typing_indicator(self, channel_type: str, chat_id: str, text: str = ""):
        """Send a typing action or status message to indicate processing."""
        if channel_type in self.adapters:
            adapter = self.adapters[channel_type]
            # Try native typing action first (Telegram supports this)
            try:
                if hasattr(adapter, 'app') and adapter.app:
                    await adapter.app.bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass

    def _welcome_key(self, message: UnifiedMessage) -> str:
        channel = str(message.channel_type or "").strip().lower()
        user_id = str(message.user_id or "").strip()
        return f"{channel}:{user_id}"

    @staticmethod
    def _is_group_like_message(message: UnifiedMessage) -> bool:
        meta = message.metadata if isinstance(getattr(message, "metadata", None), dict) else {}
        if bool(meta.get("is_group")):
            return True
        channel_id = str(getattr(message, "channel_id", "") or "").strip()
        channel_type = str(getattr(message, "channel_type", "") or "").strip().lower()
        if channel_type == "telegram" and channel_id.startswith("-"):
            return True
        if channel_type == "whatsapp" and channel_id.endswith("@g.us"):
            return True
        return False

    def _load_welcome_state(self) -> None:
        try:
            if not self._welcome_state_path.exists():
                self._welcomed_users = set()
                return
            raw = json.loads(self._welcome_state_path.read_text(encoding="utf-8"))
            items = raw.get("welcomed_users", []) if isinstance(raw, dict) else []
            if not isinstance(items, list):
                items = []
            self._welcomed_users = {str(x).strip() for x in items if str(x).strip()}
        except Exception as exc:
            logger.debug(f"Welcome state load failed: {exc}")
            self._welcomed_users = set()

    def _save_welcome_state(self) -> None:
        try:
            self._welcome_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"welcomed_users": sorted(self._welcomed_users)}
            self._welcome_state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug(f"Welcome state save failed: {exc}")

    async def _reserve_welcome_key(self, key: str) -> bool:
        async with self._welcome_lock:
            if key in self._welcomed_users:
                return False
            self._welcomed_users.add(key)
            self._save_welcome_state()
            return True

    async def _rollback_welcome_key(self, key: str) -> None:
        async with self._welcome_lock:
            if key not in self._welcomed_users:
                return
            self._welcomed_users.remove(key)
            self._save_welcome_state()

    def _build_welcome_text(self, message: UnifiedMessage) -> str:
        name = str(message.user_name or "").strip() or "merhaba"
        channel = str(message.channel_type or "").strip().lower()
        channel_label = {
            "telegram": "Telegram",
            "whatsapp": "WhatsApp",
        }.get(channel, channel.capitalize() or "Kanal")
        return (
            f"Merhaba {name}! Elyan'a hoş geldin.\n"
            f"{channel_label} bağlantın hazır.\n\n"
            "Hemen deneyebileceğin komutlar:\n"
            "- masaüstünde ne var\n"
            "- ekran görüntüsü gönder\n"
            "- köpekler hakkında araştırma yap ve rapor hazırla"
        )

    async def _maybe_send_first_contact_welcome(self, message: UnifiedMessage) -> None:
        if not self._welcome_enabled:
            return
        channel = str(message.channel_type or "").strip().lower()
        if channel not in self._welcome_channels:
            return
        if self._is_group_like_message(message):
            return

        key = self._welcome_key(message)
        should_send = await self._reserve_welcome_key(key)
        if not should_send:
            return

        try:
            welcome_text = self._build_welcome_text(message)
            await self.send_outgoing_response(
                message.channel_type,
                message.channel_id,
                UnifiedResponse(text=welcome_text, format="plain"),
            )
        except Exception as exc:
            logger.warning(f"First-contact welcome send failed ({key}): {exc}")
            await self._rollback_welcome_key(key)


    async def send_outgoing_response(self, channel_type: str, chat_id: str, response: UnifiedResponse):
        """Route a response to the correct adapter."""
        if channel_type in self.adapters:
            adapter = self.adapters[channel_type]
            normalized = self._normalize_response_for_channel(channel_type, response, adapter)
            try:
                await adapter.send_message(chat_id, normalized)
                self._mark_outgoing_message(channel_type)
            except Exception as exc:
                self._increment_counter(channel_type, "send_failures")
                logger.error(f"Send failed on channel {channel_type}: {exc}")
                # Fallback-1: Channel-safe plain text without buttons/attachments.
                fallback = self._build_plain_fallback_response(channel_type, normalized)
                try:
                    await adapter.send_message(chat_id, fallback)
                    self._mark_outgoing_message(channel_type)
                except Exception as retry_exc:
                    self._increment_counter(channel_type, "send_failures")
                    logger.error(f"Fallback plain send failed on channel {channel_type}: {retry_exc}")
                    # Fallback-2: very short plain text.
                    short_fallback = self._build_short_plain_fallback_response(channel_type, normalized)
                    try:
                        await adapter.send_message(chat_id, short_fallback)
                        self._mark_outgoing_message(channel_type)
                    except Exception as last_exc:
                        self._increment_counter(channel_type, "send_failures")
                        logger.error(f"Fallback short send failed on channel {channel_type}: {last_exc}")
        else:
            logger.warning(f"No adapter registered for channel: {channel_type}")

    async def start_all(self):
        """Start all registered adapters."""
        self._is_running = True
        initial_tasks = [
            self._connect_adapter_once(channel_type, adapter)
            for channel_type, adapter in self.adapters.items()
        ]
        if initial_tasks:
            await asyncio.gather(*initial_tasks)

        for channel_type, adapter in self.adapters.items():
            task = self._supervisor_tasks.get(channel_type)
            if task and not task.done():
                continue
            self._supervisor_tasks[channel_type] = asyncio.create_task(
                self._adapter_supervisor(channel_type, adapter),
                name=f"adapter-supervisor:{channel_type}",
            )

    async def stop_all(self):
        """Stop all registered adapters."""
        self._is_running = False
        try:
            if self._intervention_manager:
                self._intervention_manager.unregister_listener(self._on_intervention_requested)
        except Exception:
            pass

        for task in self._supervisor_tasks.values():
            task.cancel()
        if self._supervisor_tasks:
            await asyncio.gather(*self._supervisor_tasks.values(), return_exceptions=True)
        self._supervisor_tasks.clear()

        tasks = [adapter.disconnect() for adapter in self.adapters.values()]
        if tasks:
            await asyncio.gather(*tasks)

        now_ts = time.time()
        for channel_type in self.adapters:
            self._update_health(
                channel_type,
                status="stopped",
                connected=False,
                next_retry_in_s=0.0,
                last_attempt_ts=now_ts,
            )

    async def _connect_adapter_once(self, channel_type: str, adapter: BaseChannelAdapter):
        self._update_health(channel_type, status="connecting", last_attempt_ts=time.time())
        try:
            await adapter.connect()
        except Exception as exc:
            self._register_connect_failure(channel_type, str(exc))
            logger.warning(f"Initial connect failed for {channel_type}: {exc}")
            return

        status = self._safe_adapter_status(adapter)
        if status == "connected":
            now_ts = time.time()
            self._update_health(
                channel_type,
                status=status,
                connected=True,
                last_connected_ts=now_ts,
                next_retry_in_s=0.0,
            )
        else:
            # Some adapters connect asynchronously; supervisor will keep checking.
            self._update_health(
                channel_type,
                status=status or "connecting",
                connected=False,
            )

    async def _adapter_supervisor(self, channel_type: str, adapter: BaseChannelAdapter):
        cfg = getattr(adapter, "config", {}) or {}
        base_retry = max(0.5, float(cfg.get("reconnect_base_sec", 2.0)))
        max_retry = max(base_retry, float(cfg.get("reconnect_max_sec", 60.0)))
        health_interval = max(1.0, float(cfg.get("health_interval_sec", 10.0)))
        connect_grace = max(0.2, float(cfg.get("connect_grace_sec", 2.0)))
        retry_count = int(self._adapter_health.get(channel_type, {}).get("retries", 0))

        while self._is_running:
            status = self._safe_adapter_status(adapter)
            if status == "connected":
                self._update_health(
                    channel_type,
                    status="connected",
                    connected=True,
                    next_retry_in_s=0.0,
                    last_error=None,
                )
                await asyncio.sleep(health_interval)
                continue

            if status == "unavailable":
                # Missing dependency etc. No aggressive reconnect loop.
                self._update_health(
                    channel_type,
                    status="unavailable",
                    connected=False,
                    next_retry_in_s=max_retry,
                )
                await asyncio.sleep(max_retry)
                continue

            retry_count += 1
            retry_delay = min(max_retry, base_retry * (2 ** max(0, retry_count - 1)))
            self._update_health(
                channel_type,
                status="reconnecting" if retry_count > 1 else "connecting",
                connected=False,
                retries=retry_count,
                next_retry_in_s=round(retry_delay, 2),
                last_attempt_ts=time.time(),
            )
            try:
                await adapter.connect()
                await asyncio.sleep(connect_grace)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._register_connect_failure(channel_type, str(exc), retries=retry_count, next_retry_in_s=retry_delay)
                logger.warning(f"Reconnect failed for {channel_type}: {exc}")
                await asyncio.sleep(retry_delay)
                continue

            status_after = self._safe_adapter_status(adapter)
            if status_after == "connected":
                now_ts = time.time()
                retry_count = 0
                self._update_health(
                    channel_type,
                    status="connected",
                    connected=True,
                    retries=0,
                    next_retry_in_s=0.0,
                    last_connected_ts=now_ts,
                    last_error=None,
                )
                await asyncio.sleep(health_interval)
            else:
                self._register_connect_failure(
                    channel_type,
                    f"status={status_after or 'unknown'}",
                    retries=retry_count,
                    next_retry_in_s=retry_delay,
                )
                await asyncio.sleep(retry_delay)

    def _register_connect_failure(
        self,
        channel_type: str,
        error: str,
        *,
        retries: Optional[int] = None,
        next_retry_in_s: Optional[float] = None,
    ):
        health = self._adapter_health.setdefault(channel_type, {})
        failures = int(health.get("failures", 0)) + 1
        payload: Dict[str, Any] = {
            "status": "error",
            "connected": False,
            "failures": failures,
            "last_error": (error or "")[:240],
            "last_attempt_ts": time.time(),
        }
        if retries is not None:
            payload["retries"] = retries
        if next_retry_in_s is not None:
            payload["next_retry_in_s"] = round(float(next_retry_in_s), 2)
        self._update_health(channel_type, **payload)

    def _safe_adapter_status(self, adapter: BaseChannelAdapter) -> str:
        try:
            status = adapter.get_status()
            if inspect.isawaitable(status):
                # Some mocks may expose async get_status; avoid leaking warnings.
                close = getattr(status, "close", None)
                if callable(close):
                    close()
                return "unknown"
            return str(status or "unknown").lower()
        except Exception:
            return "unknown"

    def _update_health(self, channel_type: str, **kwargs):
        health = self._adapter_health.setdefault(
            channel_type,
            {
                "channel": channel_type,
                "status": "unknown",
                "connected": False,
                "retries": 0,
                "failures": 0,
                "last_error": None,
                "last_attempt_ts": None,
                "last_connected_ts": None,
                "next_retry_in_s": 0.0,
                "received_count": 0,
                "sent_count": 0,
                "send_failures": 0,
                "processing_errors": 0,
                "last_message_in_ts": None,
                "last_message_out_ts": None,
            },
        )
        health.update(kwargs)

    def _increment_counter(self, channel_type: str, key: str, amount: int = 1):
        health = self._adapter_health.setdefault(channel_type, {"channel": channel_type})
        health[key] = int(health.get(key, 0)) + int(amount)

    def _mark_incoming_message(self, channel_type: str):
        self._increment_counter(channel_type, "received_count", 1)
        self._update_health(channel_type, last_message_in_ts=time.time())

    def _mark_outgoing_message(self, channel_type: str):
        self._increment_counter(channel_type, "sent_count", 1)
        self._update_health(channel_type, last_message_out_ts=time.time())

    def get_adapter_health(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._adapter_health.items()}

    def get_adapter_status(self) -> Dict[str, str]:
        return {name: self._safe_adapter_status(adapter) for name, adapter in self.adapters.items()}
