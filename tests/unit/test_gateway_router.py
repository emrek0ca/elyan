"""
Unit testler: GatewayRouter
Adapter kayıt, mesaj yönlendirme ve hata izolasyonu.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.gateway.router import GatewayRouter
from core.gateway.message import UnifiedMessage
from core.gateway.response import UnifiedResponse


def _make_message(**kwargs):
    defaults = {
        "id": "test-001",
        "channel_type": "test",
        "channel_id": "chan-001",
        "user_id": "user-001",
        "user_name": "TestUser",
        "text": "Merhaba",
    }
    defaults.update(kwargs)
    return UnifiedMessage(**defaults)


class TestGatewayRouter:
    def _router(self):
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value="Test yanıt")
        mock_agent.current_user_id = None
        return GatewayRouter(agent=mock_agent), mock_agent

    def test_register_adapter(self):
        router, _ = self._router()
        mock_adapter = MagicMock()
        mock_adapter.on_message = MagicMock()
        router.register_adapter("test_channel", mock_adapter)
        assert "test_channel" in router.adapters
        mock_adapter.on_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_outgoing_response_calls_adapter(self):
        router, _ = self._router()
        mock_adapter = AsyncMock()
        mock_adapter.on_message = MagicMock()
        router.register_adapter("telegram", mock_adapter)

        response = UnifiedResponse(text="Merhaba!")
        await router.send_outgoing_response("telegram", "chat-123", response)
        mock_adapter.send_message.assert_called_once_with("chat-123", response)

    @pytest.mark.asyncio
    async def test_send_outgoing_response_unknown_channel(self):
        router, _ = self._router()
        # Kayıtlı olmayan kanalda send — exception fırlatmamalı
        response = UnifiedResponse(text="Test")
        try:
            await router.send_outgoing_response("nonexistent", "chat-123", response)
        except Exception as exc:
            pytest.fail(f"Bilinmeyen kanal exception fırlattı: {exc}")

    @pytest.mark.asyncio
    async def test_start_all_calls_connect(self):
        router, _ = self._router()
        a1 = AsyncMock()
        a1.on_message = MagicMock()
        a1.get_status = MagicMock(return_value="connected")
        a2 = AsyncMock()
        a2.on_message = MagicMock()
        a2.get_status = MagicMock(return_value="connected")
        router.register_adapter("ch1", a1)
        router.register_adapter("ch2", a2)
        await router.start_all()
        a1.connect.assert_called_once()
        a2.connect.assert_called_once()
        await router.stop_all()

    @pytest.mark.asyncio
    async def test_stop_all_calls_disconnect(self):
        router, _ = self._router()
        a1 = AsyncMock()
        a1.on_message = MagicMock()
        a1.get_status = MagicMock(return_value="connected")
        router.register_adapter("ch1", a1)
        await router.start_all()
        await router.stop_all()
        a1.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_incoming_message_calls_agent(self):
        """Gelen mesajda agent.process() çağrılmalı."""
        router, mock_agent = self._router()

        # Agent router'ı mock'la
        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)

            # send_outgoing_response'u da mock'la
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", text="Merhaba!")
            await router.handle_incoming_message(msg)

            mock_agent.process.assert_called_once_with("Merhaba!")

    @pytest.mark.asyncio
    async def test_handle_incoming_message_error_sends_error_response(self):
        """Agent exception fırlatırsa kullanıcıya hata mesajı gönderilmeli."""
        router, mock_agent = self._router()
        mock_agent.process = AsyncMock(side_effect=Exception("LLM hatası"))

        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message()
            await router.handle_incoming_message(msg)

            # send_outgoing_response çağrılmış olmalı (hata mesajı ile)
            router.send_outgoing_response.assert_called_once()
            sent_response = router.send_outgoing_response.call_args[0][2]
            assert isinstance(sent_response, UnifiedResponse)
            assert len(sent_response.text) > 0

    @pytest.mark.asyncio
    async def test_adapter_health_exposes_retry_and_failure(self):
        router, _ = self._router()

        class FlakyAdapter:
            def __init__(self):
                self.on_message_callback = None
                self.config = {
                    "reconnect_base_sec": 0.01,
                    "reconnect_max_sec": 0.02,
                    "health_interval_sec": 0.01,
                    "connect_grace_sec": 0.01,
                }
                self.connected = False
                self.connect_calls = 0

            def on_message(self, cb):
                self.on_message_callback = cb

            async def connect(self):
                self.connect_calls += 1
                if self.connect_calls >= 2:
                    self.connected = True
                else:
                    raise RuntimeError("temporary connect error")

            async def disconnect(self):
                self.connected = False

            async def send_message(self, chat_id, response):
                return None

            def get_status(self):
                return "connected" if self.connected else "disconnected"

            def get_capabilities(self):
                return {}

        adapter = FlakyAdapter()
        router.register_adapter("flaky", adapter)
        await router.start_all()
        await asyncio.sleep(0.06)
        health = router.get_adapter_health().get("flaky", {})
        assert adapter.connect_calls >= 2
        assert health.get("failures", 0) >= 1
        assert health.get("status") in {"connected", "connecting", "reconnecting", "error"}
        await router.stop_all()
