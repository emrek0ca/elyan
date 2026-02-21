import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from .message import UnifiedMessage
from .response import UnifiedResponse
from .adapters.base import BaseChannelAdapter
from core.multi_agent.router import agent_router
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
        self._welcome_enabled = bool(welcome_enabled)
        self._welcome_channels = {"telegram", "whatsapp"}
        self._welcome_lock = asyncio.Lock()
        self._welcomed_users: set[str] = set()
        if welcome_state_path:
            self._welcome_state_path = Path(str(welcome_state_path)).expanduser()
        else:
            self._welcome_state_path = ELYAN_DIR / "welcome_state.json"
        self._load_welcome_state()

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
        logger.info(f"Incoming: [{message.channel_type}] user={message.user_id} text={message.text[:50]}")
        self._mark_incoming_message(message.channel_type)
        await self._maybe_send_first_contact_welcome(message)
        
        try:
            agent = await agent_router.route_message(message.channel_type, message.user_id)
            agent.current_user_id = message.user_id
            
            # Notify dashboard
            try:
                from core.gateway.server import push_activity
                push_activity("message", message.channel_type, message.text[:60])
            except Exception:
                pass
            
            response_text = await agent.process(message.text)
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
            error_resp = UnifiedResponse(text="Üzgünüm, bu isteği işlerken bir hata oluştu.")
            await self.send_outgoing_response(message.channel_type, message.channel_id, error_resp)

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
            try:
                await adapter.send_message(chat_id, response)
                self._mark_outgoing_message(channel_type)
            except Exception as exc:
                self._increment_counter(channel_type, "send_failures")
                logger.error(f"Send failed on channel {channel_type}: {exc}")
                raise
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
