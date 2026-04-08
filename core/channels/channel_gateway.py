"""
core/channels/channel_gateway.py
───────────────────────────────────────────────────────────────────────────────
Unified Channel Gateway — Elyan Multi-Channel Entry Point

Manages the lifecycle of all channel adapters (Telegram, WhatsApp, iMessage,
Discord, etc.) and provides:
  - Centralized connect/disconnect with auto-reconnect
  - Auth validation per channel (whitelist + rate limiting)
  - Health monitoring and status aggregation
  - Proactive message sending (Elyan → user across any channel)

This sits above GatewayRouter, which handles message processing.
ChannelGateway handles adapter lifecycle + outbound proactive messaging.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("channel_gateway")

_RECONNECT_BASE_S = 5
_RECONNECT_MAX_S = 300
_HEALTH_CHECK_INTERVAL_S = 60


@dataclass(slots=True)
class ChannelStatus:
    """Runtime status of a channel adapter."""
    channel_type: str
    connected: bool = False
    enabled: bool = True
    last_connected_ts: float = 0.0
    last_error: str = ""
    reconnect_attempts: int = 0
    messages_in: int = 0
    messages_out: int = 0


class RateLimiter:
    """Token bucket rate limiter per (channel, user)."""

    def __init__(self, rate: float = 1.0, burst: int = 5) -> None:
        self._rate = rate      # tokens per second
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}  # key → (tokens, last_ts)

    def allow(self, key: str) -> bool:
        now = time.time()
        tokens, last_ts = self._buckets.get(key, (float(self._burst), now))
        elapsed = now - last_ts
        tokens = min(self._burst, tokens + elapsed * self._rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True
        self._buckets[key] = (tokens, now)
        return False


class ChannelGateway:
    """Manages channel adapter lifecycle and provides proactive messaging."""

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}  # channel_type → BaseChannelAdapter
        self._statuses: dict[str, ChannelStatus] = {}
        self._allowed_users: dict[str, set[str]] = {}  # channel → whitelist (empty=all)
        self._rate_limiter = RateLimiter(rate=1.0, burst=5)
        self._running = False
        self._health_task: asyncio.Task | None = None
        self._reconnect_tasks: dict[str, asyncio.Task] = {}

    # ── Registration ────────────────────────────────────────────────────────

    def register(self, channel_type: str, adapter: Any, *, allowed_users: set[str] | None = None) -> None:
        """Register an adapter with optional user whitelist."""
        self._adapters[channel_type] = adapter
        self._statuses[channel_type] = ChannelStatus(channel_type=channel_type)
        if allowed_users:
            self._allowed_users[channel_type] = allowed_users
        logger.info(f"Channel registered: {channel_type}")

    # ── Auth ────────────────────────────────────────────────────────────────

    def is_user_allowed(self, channel_type: str, user_id: str) -> bool:
        """Check if user is allowed on this channel."""
        whitelist = self._allowed_users.get(channel_type)
        if not whitelist:
            return True  # No whitelist = open
        return user_id in whitelist

    def check_rate_limit(self, channel_type: str, user_id: str) -> bool:
        """Check if user is within rate limit."""
        return self._rate_limiter.allow(f"{channel_type}:{user_id}")

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def connect_all(self) -> dict[str, bool]:
        """Connect all registered adapters. Returns {channel: success}."""
        results: dict[str, bool] = {}
        tasks = []
        for ctype, adapter in self._adapters.items():
            tasks.append((ctype, self._connect_one(ctype, adapter)))

        for ctype, coro in tasks:
            try:
                await coro
                results[ctype] = True
            except Exception as exc:
                logger.warning(f"Channel {ctype} connect failed: {exc}")
                results[ctype] = False

        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())
        return results

    async def _connect_one(self, channel_type: str, adapter: Any) -> None:
        """Connect a single adapter with status tracking."""
        status = self._statuses[channel_type]
        try:
            await adapter.connect()
            status.connected = True
            status.last_connected_ts = time.time()
            status.reconnect_attempts = 0
            status.last_error = ""
            logger.info(f"Channel connected: {channel_type}")
        except Exception as exc:
            status.connected = False
            status.last_error = str(exc)[:200]
            raise

    async def disconnect_all(self) -> None:
        """Gracefully disconnect all adapters."""
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        for task in self._reconnect_tasks.values():
            if not task.done():
                task.cancel()

        for ctype, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
                self._statuses[ctype].connected = False
                logger.info(f"Channel disconnected: {ctype}")
            except Exception as exc:
                logger.warning(f"Channel {ctype} disconnect error: {exc}")

    # ── Auto-Reconnect ──────────────────────────────────────────────────────

    async def _schedule_reconnect(self, channel_type: str) -> None:
        """Schedule exponential backoff reconnection."""
        if channel_type in self._reconnect_tasks:
            task = self._reconnect_tasks[channel_type]
            if not task.done():
                return

        self._reconnect_tasks[channel_type] = asyncio.create_task(
            self._reconnect_loop(channel_type)
        )

    async def _reconnect_loop(self, channel_type: str) -> None:
        status = self._statuses.get(channel_type)
        adapter = self._adapters.get(channel_type)
        if not status or not adapter:
            return

        while self._running and not status.connected:
            status.reconnect_attempts += 1
            delay = min(
                _RECONNECT_BASE_S * (2 ** (status.reconnect_attempts - 1)),
                _RECONNECT_MAX_S,
            )
            logger.info(f"Channel {channel_type}: reconnect attempt {status.reconnect_attempts} in {delay}s")
            await asyncio.sleep(delay)

            try:
                await self._connect_one(channel_type, adapter)
                logger.info(f"Channel {channel_type}: reconnected successfully")
            except Exception as exc:
                logger.warning(f"Channel {channel_type}: reconnect failed: {exc}")

    # ── Health Check ────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL_S)
            for ctype, adapter in self._adapters.items():
                status = self._statuses[ctype]
                if not status.enabled:
                    continue
                try:
                    adapter_status = adapter.get_status()
                    if adapter_status in ("disconnected", "error"):
                        status.connected = False
                        await self._schedule_reconnect(ctype)
                except Exception:
                    pass

    # ── Proactive Messaging (Elyan → User) ─────────────────────────────────

    async def send_proactive(
        self,
        channel_type: str,
        chat_id: str,
        text: str,
        *,
        attachments: list[dict] | None = None,
        buttons: list[dict] | None = None,
    ) -> bool:
        """Send a message from Elyan to user on any channel.

        Used for proactive alerts, scheduled reports, etc.
        """
        from core.gateway.response import UnifiedResponse

        adapter = self._adapters.get(channel_type)
        if not adapter:
            logger.warning(f"Proactive send failed: no adapter for {channel_type}")
            return False

        status = self._statuses.get(channel_type)
        if not status or not status.connected:
            logger.warning(f"Proactive send failed: {channel_type} not connected")
            return False

        response = UnifiedResponse(
            text=text,
            attachments=attachments or [],
            buttons=buttons or [],
            format="markdown",
        )
        try:
            await adapter.send_message(chat_id, response)
            status.messages_out += 1
            return True
        except Exception as exc:
            logger.error(f"Proactive send to {channel_type}:{chat_id} failed: {exc}")
            return False

    async def broadcast(
        self,
        text: str,
        chat_ids: dict[str, str] | None = None,
    ) -> dict[str, bool]:
        """Send message to user across all connected channels.

        Args:
            text: Message text
            chat_ids: {channel_type: chat_id} mapping. If None, sends to all.
        """
        results: dict[str, bool] = {}
        targets = chat_ids or {}
        for ctype in targets:
            ok = await self.send_proactive(ctype, targets[ctype], text)
            results[ctype] = ok
        return results

    # ── Status ──────────────────────────────────────────────────────────────

    def get_all_status(self) -> list[dict[str, Any]]:
        return [
            {
                "channel": s.channel_type,
                "connected": s.connected,
                "enabled": s.enabled,
                "messages_in": s.messages_in,
                "messages_out": s.messages_out,
                "last_error": s.last_error,
                "reconnect_attempts": s.reconnect_attempts,
            }
            for s in self._statuses.values()
        ]

    def get_connected_channels(self) -> list[str]:
        return [s.channel_type for s in self._statuses.values() if s.connected]

    def increment_in(self, channel_type: str) -> None:
        s = self._statuses.get(channel_type)
        if s:
            s.messages_in += 1

    def increment_out(self, channel_type: str) -> None:
        s = self._statuses.get(channel_type)
        if s:
            s.messages_out += 1


# ── Singleton ───────────────────────────────────────────────────────────────

_instance: ChannelGateway | None = None


def get_channel_gateway() -> ChannelGateway:
    global _instance
    if _instance is None:
        _instance = ChannelGateway()
    return _instance


__all__ = ["ChannelGateway", "ChannelStatus", "RateLimiter", "get_channel_gateway"]
