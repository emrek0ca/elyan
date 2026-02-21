"""
Unit testler: Gateway kanal adaptörleri
Gerçek ağ bağlantısı gerektirmeyen mock tabanlı testler.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.gateway.adapters import ADAPTER_REGISTRY, get_adapter_class
from core.gateway.adapters.base import BaseChannelAdapter
from core.gateway.message import UnifiedMessage
from core.gateway.response import UnifiedResponse


# ── ADAPTER_REGISTRY ─────────────────────────────────────────────────────────

class TestAdapterRegistry:
    def test_all_expected_adapters_registered(self):
        expected = {
            "telegram", "discord", "slack", "whatsapp",
            "webchat", "signal", "matrix", "teams",
            "google_chat", "imessage",
        }
        assert expected == set(ADAPTER_REGISTRY.keys())

    def test_get_adapter_class_returns_correct_type(self):
        from core.gateway.adapters.signal_adapter import SignalAdapter
        from core.gateway.adapters.matrix_adapter import MatrixAdapter
        from core.gateway.adapters.teams_adapter import TeamsAdapter
        from core.gateway.adapters.google_chat_adapter import GoogleChatAdapter
        from core.gateway.adapters.imessage_adapter import IMessageAdapter

        assert get_adapter_class("signal") is SignalAdapter
        assert get_adapter_class("matrix") is MatrixAdapter
        assert get_adapter_class("teams") is TeamsAdapter
        assert get_adapter_class("google_chat") is GoogleChatAdapter
        assert get_adapter_class("imessage") is IMessageAdapter

    def test_get_adapter_class_unknown_returns_none(self):
        assert get_adapter_class("fax_machine") is None

    def test_all_adapters_subclass_base(self):
        for name, cls in ADAPTER_REGISTRY.items():
            assert issubclass(cls, BaseChannelAdapter), f"{name} BaseChannelAdapter'dan türemeli"


# ── Signal Adapter ────────────────────────────────────────────────────────────

class TestSignalAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.signal_adapter import SignalAdapter
        cfg = {"phone_number": "+905551234567", **kwargs}
        return SignalAdapter(cfg)

    def test_init_defaults(self):
        adapter = self._make()
        assert adapter.phone_number == "+905551234567"
        assert not adapter._is_connected
        assert adapter.get_status() == "disconnected"

    def test_connect_missing_phone_does_not_connect(self):
        from core.gateway.adapters.signal_adapter import SignalAdapter
        adapter = SignalAdapter({})
        asyncio.run(adapter.connect())
        assert not adapter._is_connected

    def test_get_capabilities_has_required_keys(self):
        caps = self._make().get_capabilities()
        assert "text" in caps
        assert "groups" in caps

    @pytest.mark.asyncio
    async def test_process_envelope_fires_callback(self):
        adapter = self._make(http_url="http://localhost:8080")
        received = []
        adapter.on_message(lambda m: received.append(m))

        envelope = {
            "data": {
                "source": "+905551234567",
                "dataMessage": {"message": "Merhaba"},
            }
        }
        await adapter._process_envelope(envelope)
        assert len(received) == 1
        assert received[0].text == "Merhaba"
        assert received[0].channel_type == "signal"

    @pytest.mark.asyncio
    async def test_process_envelope_empty_body_ignored(self):
        adapter = self._make()
        received = []
        adapter.on_message(lambda m: received.append(m))
        await adapter._process_envelope({"data": {"dataMessage": {"message": ""}}})
        assert not received

    @pytest.mark.asyncio
    async def test_send_http_posts_correct_payload(self):
        adapter = self._make(http_url="http://localhost:8080")
        adapter._is_connected = True

        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        adapter._session = mock_session

        response = UnifiedResponse(text="Test mesajı")
        await adapter.send_message("+905559876543", response)

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["message"] == "Test mesajı"
        assert "+905559876543" in payload["recipients"]


# ── Matrix Adapter ────────────────────────────────────────────────────────────

class TestMatrixAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.matrix_adapter import MatrixAdapter
        cfg = {
            "homeserver": "https://matrix.org",
            "user_id": "@elyan:matrix.org",
            "access_token": "syt_test",
            **kwargs,
        }
        return MatrixAdapter(cfg)

    def test_init_defaults(self):
        adapter = self._make()
        assert adapter.homeserver == "https://matrix.org"
        assert adapter.user_id == "@elyan:matrix.org"
        assert not adapter._is_connected

    def test_connect_missing_credentials(self):
        from core.gateway.adapters.matrix_adapter import MatrixAdapter
        adapter = MatrixAdapter({"homeserver": "https://matrix.org"})
        asyncio.run(adapter.connect())
        assert not adapter._is_connected

    def test_get_capabilities(self):
        caps = self._make().get_capabilities()
        assert caps["markdown"] is True
        assert caps["e2e"] is True

    @pytest.mark.asyncio
    async def test_on_room_message_fires_callback(self):
        adapter = self._make()
        adapter._is_connected = True
        adapter.user_id = "@elyan:matrix.org"

        received = []
        adapter.on_message(lambda m: received.append(m))

        room = MagicMock()
        room.room_id = "!abc:matrix.org"
        room.display_name = "Test Room"
        room.user_name = MagicMock(return_value="TestUser")

        event = MagicMock()
        event.event_id = "$evt123"
        event.sender = "@user:matrix.org"
        event.body = "Merhaba Elyan!"

        await adapter._on_room_message(room, event)
        assert len(received) == 1
        assert received[0].text == "Merhaba Elyan!"
        assert received[0].channel_type == "matrix"

    @pytest.mark.asyncio
    async def test_own_message_ignored(self):
        adapter = self._make()
        adapter.user_id = "@elyan:matrix.org"
        received = []
        adapter.on_message(lambda m: received.append(m))

        room = MagicMock()
        room.room_id = "!abc:matrix.org"
        room.display_name = "Test Room"
        room.user_name = MagicMock(return_value="Elyan")

        event = MagicMock()
        event.event_id = "$own"
        event.sender = "@elyan:matrix.org"  # kendi mesajı
        event.body = "Bu benim mesajım"

        await adapter._on_room_message(room, event)
        assert not received


# ── Teams Adapter ─────────────────────────────────────────────────────────────

class TestTeamsAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.teams_adapter import TeamsAdapter
        cfg = {
            "app_id": "test-app-id",
            "app_password": "test-password",
            **kwargs,
        }
        return TeamsAdapter(cfg)

    def test_init_defaults(self):
        adapter = self._make()
        assert adapter.app_id == "test-app-id"
        assert adapter.webhook_path == "/api/teams/messages"
        assert not adapter._is_connected

    def test_get_capabilities(self):
        caps = self._make().get_capabilities()
        assert caps["adaptive_cards"] is True
        assert caps["threads"] is True

    @pytest.mark.asyncio
    async def test_handle_webhook_message_fires_callback(self):
        adapter = self._make()
        received = []
        adapter.on_message(lambda m: asyncio.create_task(_append(received, m)))

        async def _append(lst, item):
            lst.append(item)

        activity = {
            "type": "message",
            "id": "msg-001",
            "text": "Merhaba <at>Elyan</at>",
            "from": {"id": "user-001", "name": "Emre"},
            "conversation": {"id": "conv-001", "conversationType": "personal"},
            "serviceUrl": "https://smba.trafficmanager.net/apis",
        }

        request = MagicMock()
        request.read = AsyncMock(return_value=json.dumps(activity).encode())
        resp = await adapter.handle_webhook(request)
        assert resp.status == 202
        # Callback asyncio.create_task ile çalışıyor, kısa bekle
        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].text == "Merhaba"  # @mention temizlendi

    @pytest.mark.asyncio
    async def test_handle_webhook_non_message_returns_202(self):
        adapter = self._make()
        activity = {"type": "conversationUpdate"}
        request = MagicMock()
        request.read = AsyncMock(return_value=json.dumps(activity).encode())
        resp = await adapter.handle_webhook(request)
        assert resp.status == 202


# ── Google Chat Adapter ───────────────────────────────────────────────────────

class TestGoogleChatAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.google_chat_adapter import GoogleChatAdapter
        cfg = {"mode": "webhook", "webhook_url": "https://chat.googleapis.com/v1/...", **kwargs}
        return GoogleChatAdapter(cfg)

    def test_init_webhook_mode(self):
        adapter = self._make()
        assert adapter.mode == "webhook"
        assert not adapter._is_connected

    def test_get_capabilities_webhook(self):
        caps = self._make().get_capabilities()
        assert caps["cards"] is False  # webhook modunda card yok
        assert caps["threads"] is True

    def test_get_capabilities_bot(self):
        from core.gateway.adapters.google_chat_adapter import GoogleChatAdapter
        adapter = GoogleChatAdapter({"mode": "bot"})
        caps = adapter.get_capabilities()
        assert caps["cards"] is True

    @pytest.mark.asyncio
    async def test_process_event_fires_callback(self):
        adapter = self._make()
        received = []
        adapter.on_message(lambda m: received.append(m))

        event = {
            "type": "MESSAGE",
            "space": {"name": "spaces/abc123", "type": "ROOM"},
            "message": {
                "name": "spaces/abc123/messages/msg001",
                "text": "Merhaba",
                "argumentText": "Merhaba",
                "sender": {"name": "users/user001", "displayName": "Emre"},
                "thread": {"name": "spaces/abc123/threads/thr001"},
            },
        }
        await adapter._process_event(event)
        assert len(received) == 1
        assert received[0].text == "Merhaba"
        assert received[0].channel_type == "google_chat"

    @pytest.mark.asyncio
    async def test_send_webhook(self):
        adapter = self._make()
        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        adapter._session = mock_session

        await adapter.send_message("spaces/abc123", UnifiedResponse(text="Test"))
        mock_session.post.assert_called_once()
        payload = mock_session.post.call_args[1]["json"]
        assert payload["text"] == "Test"


# ── iMessage Adapter ──────────────────────────────────────────────────────────

class TestIMessageAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.imessage_adapter import IMessageAdapter
        cfg = {
            "server_url": "http://localhost:1234",
            "password": "test123",
            **kwargs,
        }
        return IMessageAdapter(cfg)

    def test_init_defaults(self):
        adapter = self._make()
        assert adapter.server_url == "http://localhost:1234"
        assert not adapter._is_connected

    def test_connect_missing_config(self):
        from core.gateway.adapters.imessage_adapter import IMessageAdapter
        adapter = IMessageAdapter({})
        asyncio.run(adapter.connect())
        assert not adapter._is_connected

    def test_get_capabilities(self):
        caps = self._make().get_capabilities()
        assert caps["reactions"] is True
        assert caps["read_receipts"] is True
        assert caps["buttons"] is False

    @pytest.mark.asyncio
    async def test_process_message_fires_callback(self):
        adapter = self._make()
        received = []
        adapter.on_message(lambda m: received.append(m))

        data = {
            "message": {
                "guid": "msg-001",
                "text": "Merhaba",
                "isFromMe": False,
                "itemType": 0,
                "handle": {"address": "+905551111111"},
                "chats": [{"guid": "chat-001", "isGroupChat": False}],
            }
        }
        await adapter._process_message(data)
        assert len(received) == 1
        assert received[0].text == "Merhaba"
        assert received[0].channel_type == "imessage"

    @pytest.mark.asyncio
    async def test_own_message_ignored(self):
        adapter = self._make()
        received = []
        adapter.on_message(lambda m: received.append(m))

        data = {
            "message": {
                "guid": "msg-002",
                "text": "Kendi mesajım",
                "isFromMe": True,
                "itemType": 0,
                "chats": [{"guid": "chat-001"}],
            }
        }
        await adapter._process_message(data)
        assert not received

    @pytest.mark.asyncio
    async def test_send_message_posts_correct_payload(self):
        adapter = self._make()
        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        adapter._session = mock_session

        await adapter.send_message("iMessage;-;+905551111111", UnifiedResponse(text="Merhaba"))
        mock_session.post.assert_called_once()
        payload = mock_session.post.call_args[1]["json"]
        assert payload["message"] == "Merhaba"
        assert payload["chatGuid"] == "iMessage;-;+905551111111"

    @pytest.mark.asyncio
    async def test_allowed_chats_filter(self):
        adapter = self._make(allowed_chats=["allowed-chat-001"])
        received = []
        adapter.on_message(lambda m: received.append(m))

        # İzin verilmeyen sohbet
        data = {
            "message": {
                "guid": "msg-003",
                "text": "Bu engellendi",
                "isFromMe": False,
                "itemType": 0,
                "handle": {"address": "+905551111111"},
                "chats": [{"guid": "other-chat-999"}],
            }
        }
        await adapter._process_message(data)
        assert not received

        # İzin verilen sohbet
        data["message"]["chats"][0]["guid"] = "allowed-chat-001"
        await adapter._process_message(data)
        assert len(received) == 1
