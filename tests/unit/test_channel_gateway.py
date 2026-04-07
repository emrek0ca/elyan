"""Tests for ChannelGateway — lifecycle, auth, rate limiting, proactive messaging."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.channels.channel_gateway import ChannelGateway, RateLimiter


@pytest.fixture
def gw():
    return ChannelGateway()


@pytest.fixture
def mock_adapter():
    a = MagicMock()
    a.connect = AsyncMock()
    a.disconnect = AsyncMock()
    a.send_message = AsyncMock()
    a.get_status = MagicMock(return_value="connected")
    a.get_capabilities = MagicMock(return_value={"text": True})
    return a


def test_register(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    assert "telegram" in gw._adapters
    assert gw._statuses["telegram"].channel_type == "telegram"


def test_whitelist_allows(gw, mock_adapter):
    gw.register("telegram", mock_adapter, allowed_users={"user1", "user2"})
    assert gw.is_user_allowed("telegram", "user1") is True
    assert gw.is_user_allowed("telegram", "user3") is False


def test_no_whitelist_allows_all(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    assert gw.is_user_allowed("telegram", "anyone") is True


def test_rate_limiter():
    rl = RateLimiter(rate=1.0, burst=3)
    assert rl.allow("user1") is True
    assert rl.allow("user1") is True
    assert rl.allow("user1") is True
    assert rl.allow("user1") is False  # burst exhausted


@pytest.mark.asyncio
async def test_connect_all(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    results = await gw.connect_all()
    assert results["telegram"] is True
    assert gw._statuses["telegram"].connected is True
    mock_adapter.connect.assert_called_once()
    await gw.disconnect_all()


@pytest.mark.asyncio
async def test_connect_failure(gw):
    bad_adapter = MagicMock()
    bad_adapter.connect = AsyncMock(side_effect=ConnectionError("refused"))
    bad_adapter.disconnect = AsyncMock()
    gw.register("whatsapp", bad_adapter)
    results = await gw.connect_all()
    assert results["whatsapp"] is False
    assert gw._statuses["whatsapp"].connected is False
    await gw.disconnect_all()


@pytest.mark.asyncio
async def test_proactive_send(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    gw._statuses["telegram"].connected = True
    ok = await gw.send_proactive("telegram", "chat123", "Hello from Jarvis!")
    assert ok is True
    mock_adapter.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_proactive_send_disconnected(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    gw._statuses["telegram"].connected = False
    ok = await gw.send_proactive("telegram", "chat123", "Hello")
    assert ok is False


def test_get_all_status(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    gw.register("whatsapp", mock_adapter)
    statuses = gw.get_all_status()
    assert len(statuses) == 2


def test_increment_counters(gw, mock_adapter):
    gw.register("telegram", mock_adapter)
    gw.increment_in("telegram")
    gw.increment_in("telegram")
    gw.increment_out("telegram")
    assert gw._statuses["telegram"].messages_in == 2
    assert gw._statuses["telegram"].messages_out == 1
