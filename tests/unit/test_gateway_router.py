"""
Unit testler: GatewayRouter
Adapter kayıt, mesaj yönlendirme ve hata izolasyonu.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from core.gateway.router import GatewayRouter
from core.gateway.message import UnifiedMessage
from core.gateway.response import UnifiedResponse
from core.channel_delivery import channel_delivery_bridge


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
    def _router(self, *, welcome_enabled: bool = False, welcome_state_path: str | None = None):
        mock_agent = AsyncMock()
        mock_agent.process = AsyncMock(return_value="Test yanıt")
        mock_agent.current_user_id = None
        return GatewayRouter(
            agent=mock_agent,
            welcome_enabled=welcome_enabled,
            welcome_state_path=welcome_state_path,
        ), mock_agent

    def test_register_adapter(self):
        router, _ = self._router()
        mock_adapter = MagicMock()
        mock_adapter.on_message = MagicMock()
        router.register_adapter("test_channel", mock_adapter)
        assert "test_channel" in router.adapters
        mock_adapter.on_message.assert_called_once()

    def test_router_registers_channel_delivery_sender(self):
        router, _ = self._router()
        assert callable(channel_delivery_bridge._sender)
        assert channel_delivery_bridge._sender.__self__ is router

    @pytest.mark.asyncio
    async def test_send_outgoing_response_calls_adapter(self):
        router, _ = self._router()
        mock_adapter = AsyncMock()
        mock_adapter.on_message = MagicMock()
        mock_adapter.get_capabilities = MagicMock(return_value={"markdown": True, "buttons": True, "images": True, "files": True})
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
    async def test_send_outgoing_response_normalizes_by_channel_capabilities(self):
        router, _ = self._router()

        class _Adapter:
            def __init__(self):
                self.sent = []

            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                self.sent.append((chat_id, response))

            def get_capabilities(self):
                return {"markdown": False, "buttons": False, "images": False, "files": False}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("test_channel", adapter)
        response = UnifiedResponse(
            text="X" * 4500,
            format="markdown",
            buttons=[{"text": "Onayla", "callback_data": "x"}],
            attachments=[{"path": "/tmp/a.png", "type": "image"}],
        )
        await router.send_outgoing_response("test_channel", "chat-1", response)
        assert len(adapter.sent) == 1
        sent = adapter.sent[0][1]
        assert sent.format == "plain"
        assert sent.buttons == []
        assert sent.attachments == []
        assert len(sent.text) <= 3500
        assert "kısaltıldı" in sent.text

    @pytest.mark.asyncio
    async def test_send_outgoing_response_preserves_attachment_summary_when_channel_cannot_send_files(self):
        router, _ = self._router()

        class _Adapter:
            def __init__(self):
                self.sent = []

            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                self.sent.append((chat_id, response))

            def get_capabilities(self):
                return {"markdown": False, "buttons": False, "images": False, "files": False}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("fallback_channel", adapter)
        response = UnifiedResponse(
            text="Rapor hazır",
            attachments=[{"path": "/tmp/report.docx", "name": "report.docx", "type": "file"}],
        )
        await router.send_outgoing_response("fallback_channel", "chat-9", response)
        sent = adapter.sent[0][1]
        assert sent.attachments == []
        assert "Dosyalar:" in sent.text
        assert "report.docx" in sent.text

    @pytest.mark.asyncio
    async def test_handle_incoming_message_preserves_agent_response_metadata(self):
        router, mock_agent = self._router()

        envelope = SimpleNamespace(
            text="Aktif gorevler:\n- away_1 [running] rapor",
            attachments=[],
            evidence_manifest_path="",
            run_id="run_meta",
            status="success",
            metadata={"task_list": [{"task_id": "away_1", "state": "running"}]},
            to_unified_attachments=lambda: [],
        )
        mock_agent.process_envelope = AsyncMock(return_value=envelope)

        class _Adapter:
            def __init__(self):
                self.sent = []

            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                self.sent.append((chat_id, response))

            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("test", adapter)

        async def _fake_route_message(channel_type, user_id):
            _ = (channel_type, user_id)
            return mock_agent

        from core.gateway import router as gateway_router_module

        original = gateway_router_module.agent_router.route_message
        gateway_router_module.agent_router.route_message = _fake_route_message
        try:
            await router.handle_incoming_message(_make_message(channel_type="test"))
        finally:
            gateway_router_module.agent_router.route_message = original

        sent = adapter.sent[-1][1]
        assert sent.metadata["run_id"] == "run_meta"
        assert sent.metadata["task_list"][0]["task_id"] == "away_1"

    @pytest.mark.asyncio
    async def test_normalize_response_adds_task_inbox_buttons_for_button_channels(self):
        router, _ = self._router()

        class _Adapter:
            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                _ = (chat_id, response)

            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("telegram", adapter)
        response = UnifiedResponse(
            text="Aktif gorevler",
            metadata={"task_list": [{"task_id": "away_77", "state": "running"}]},
        )
        normalized = GatewayRouter._normalize_response_for_channel("telegram", response, adapter)
        assert normalized.buttons
        assert normalized.buttons[0]["callback_data"] == "task|status|away_77"

    @pytest.mark.asyncio
    async def test_normalize_response_adds_resume_suggestion_buttons(self):
        router, _ = self._router()

        class _Adapter:
            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                _ = (chat_id, response)

            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("telegram", adapter)
        response = UnifiedResponse(
            text="Tamamlandı.\n\nİstersen yarım kalan göreve devam edebilirim.",
            metadata={"task_suggestion": {"task_id": "away_88", "suggested_action": "retry", "state": "failed"}},
        )
        normalized = GatewayRouter._normalize_response_for_channel("telegram", response, adapter)
        assert normalized.buttons
        assert normalized.buttons[0]["text"] == "Devam Et"
        assert normalized.buttons[0]["callback_data"] == "task|retry|away_88"

    def test_normalize_response_strips_internal_planning_markers(self):
        class _Adapter:
            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

        response = UnifiedResponse(
            text="Merhaba!\nDeliverable Spec: Kullanıcıya yardımcı olmak\nDone Criteria: Memnuniyet\n\nNasıl yardımcı olayım?"
        )
        normalized = GatewayRouter._normalize_response_for_channel("telegram", response, _Adapter())
        assert "Deliverable Spec" not in normalized.text
        assert "Done Criteria" not in normalized.text
        assert normalized.text == "Merhaba!\n\nNasıl yardımcı olayım?"

    def test_normalize_response_compacts_verbose_greeting(self):
        class _Adapter:
            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

        response = UnifiedResponse(
            text=(
                "Merhaba! Görünen o ki, tekrar selamlaşma yapıyoruz. "
                "Size nasıl yardımcı olabilirim? Lütfen bir konu belirtiniz "
                "ki size yardımcı olayım. İsterseniz önceki konulara da dönebiliriz."
            )
        )
        normalized = GatewayRouter._normalize_response_for_channel("telegram", response, _Adapter())
        assert normalized.text == "Merhaba. Nasıl yardımcı olayım?"

    def test_normalize_response_strips_system_note_and_completion_gate_lines(self):
        class _Adapter:
            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

        response = UnifiedResponse(
            text=(
                "Fatih Terim eski futbolcu ve teknik direktördür.\n"
                "Sistem notu: Yüksek Bellek kullanımı şu an %86.\n"
                "- Kullanıcının ihtiyacını belirlemek\n"
                "❌ Completion gate failed: completion:no_successful_tool_result"
            )
        )
        normalized = GatewayRouter._normalize_response_for_channel("telegram", response, _Adapter())
        assert normalized.text == "Fatih Terim eski futbolcu ve teknik direktördür."

    @pytest.mark.asyncio
    async def test_send_outgoing_response_retries_with_plain_fallback_on_error(self):
        router, _ = self._router()

        class _Adapter:
            def __init__(self):
                self.calls = 0
                self.payloads = []

            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                self.calls += 1
                self.payloads.append((chat_id, response))
                if self.calls == 1:
                    raise RuntimeError("primary send failed")

            def get_capabilities(self):
                return {"markdown": True, "buttons": True, "images": True, "files": True}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("retry_channel", adapter)
        response = UnifiedResponse(text="Merhaba", format="markdown", buttons=[{"text": "B", "callback_data": "c"}])
        await router.send_outgoing_response("retry_channel", "chat-2", response)
        assert adapter.calls == 2
        fallback = adapter.payloads[-1][1]
        assert fallback.format == "plain"
        assert fallback.buttons == []
        assert fallback.attachments == []

    @pytest.mark.asyncio
    async def test_send_outgoing_response_does_not_raise_when_both_attempts_fail(self):
        router, _ = self._router()

        class _Adapter:
            def on_message(self, cb):
                _ = cb

            async def send_message(self, chat_id, response):
                _ = (chat_id, response)
                raise RuntimeError("send failed")

            def get_capabilities(self):
                return {"markdown": True}

            async def connect(self):
                return None

            async def disconnect(self):
                return None

            def get_status(self):
                return "connected"

        adapter = _Adapter()
        router.register_adapter("fail_channel", adapter)
        response = UnifiedResponse(text="Merhaba")
        await router.send_outgoing_response("fail_channel", "chat-3", response)

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

            mock_agent.process.assert_called_once()
            called_args, called_kwargs = mock_agent.process.call_args
            assert called_args == ("Merhaba!",)
            assert "notify" in called_kwargs
            assert called_kwargs["metadata"]["channel_type"] == "telegram"
            assert called_kwargs["metadata"]["channel_id"] == "chan-001"
            assert called_kwargs["metadata"]["user_id"] == "user-001"

    @pytest.mark.asyncio
    async def test_handle_incoming_message_forwards_attachments_to_process_envelope(self):
        router, mock_agent = self._router()
        mock_agent.process_envelope = AsyncMock(
            return_value=SimpleNamespace(
                text="ok",
                attachments=[],
                evidence_manifest_path="",
                run_id="run1",
                status="success",
                to_unified_attachments=lambda: [],
            )
        )

        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(
                channel_type="telegram",
                text="Bunu duvar kağıdı yap",
                attachments=[{"path": "/tmp/dog.png", "type": "image"}],
            )
            await router.handle_incoming_message(msg)

            mock_agent.process_envelope.assert_called_once()
            _, called_kwargs = mock_agent.process_envelope.call_args
            assert called_kwargs["attachments"][0]["path"] == "/tmp/dog.png"
            assert called_kwargs["metadata"]["channel_type"] == "telegram"
            assert called_kwargs["metadata"]["channel_id"] == "chan-001"
            assert called_kwargs["metadata"]["user_id"] == "user-001"

    @pytest.mark.asyncio
    async def test_handle_incoming_message_does_not_attach_manifest_without_explicit_share_flag(self):
        router, mock_agent = self._router()
        mock_agent.process_envelope = AsyncMock(
            return_value=SimpleNamespace(
                text="ok",
                attachments=[],
                evidence_manifest_path="/tmp/manifest.json",
                run_id="run1",
                status="success",
                metadata={},
                to_unified_attachments=lambda: [],
            )
        )

        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", text="raporu hazırla")
            await router.handle_incoming_message(msg)

            sent_response = router.send_outgoing_response.call_args[0][2]
            assert sent_response.attachments == []

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

    @pytest.mark.asyncio
    async def test_first_contact_welcome_sent_once_for_telegram(self, tmp_path):
        state_path = tmp_path / "welcome_state.json"
        router, mock_agent = self._router(welcome_enabled=True, welcome_state_path=str(state_path))

        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", channel_id="123", user_id="123", user_name="Emre", text="merhaba")
            await router.handle_incoming_message(msg)
            assert router.send_outgoing_response.await_count == 2
            first_response = router.send_outgoing_response.await_args_list[0].args[2]
            assert isinstance(first_response, UnifiedResponse)
            assert "hoş geldin" in first_response.text.lower()

            router.send_outgoing_response.reset_mock()
            await router.handle_incoming_message(msg)
            assert router.send_outgoing_response.await_count == 1

    @pytest.mark.asyncio
    async def test_first_contact_welcome_skips_groups(self, tmp_path):
        state_path = tmp_path / "welcome_state.json"
        router, mock_agent = self._router(welcome_enabled=True, welcome_state_path=str(state_path))

        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock(return_value=mock_agent)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(
                channel_type="whatsapp",
                channel_id="123456@g.us",
                user_id="905551112233",
                user_name="Group User",
                text="selam",
                metadata={"is_group": True},
            )
            await router.handle_incoming_message(msg)
            assert router.send_outgoing_response.await_count == 1

    @pytest.mark.asyncio
    async def test_handle_incoming_message_resolves_pending_intervention(self):
        class _FakeInterventionManager:
            def __init__(self):
                self.pending = [
                    {
                        "id": "int-1",
                        "prompt": "Kritik işlem onayı gerekiyor",
                        "options": ["Onayla", "İptal Et"],
                        "context": {"user_id": "123"},
                        "ts": 1.0,
                    }
                ]
                self.resolved = []
                self.listeners = []

            def register_listener(self, listener):
                self.listeners.append(listener)

            def list_pending(self):
                return list(self.pending)

            def resolve(self, request_id, response):
                self.resolved.append((request_id, response))
                return True

        fake_manager = _FakeInterventionManager()
        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.get_intervention_manager", lambda: fake_manager)
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router, _ = self._router()
            router.send_outgoing_response = AsyncMock()

            first = _make_message(channel_type="telegram", channel_id="chat-1", user_id="123", text="onayla")
            await router.handle_incoming_message(first)
            assert fake_manager.resolved == []
            assert router.send_outgoing_response.await_count == 1
            sent = router.send_outgoing_response.await_args_list[0].args[2]
            assert isinstance(sent, UnifiedResponse)
            assert "onay kodu" in sent.text.lower()

            code = router._approval_codes["int-1"]["code"]
            router.send_outgoing_response.reset_mock()
            second = _make_message(channel_type="telegram", channel_id="chat-1", user_id="123", text=f"ONAY {code}")
            await router.handle_incoming_message(second)
            assert fake_manager.resolved == [("int-1", "Onayla")]
            sent2 = router.send_outgoing_response.await_args_list[0].args[2]
            assert "onay alındı" in sent2.text.lower()
            mock_ar.route_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_incoming_message_resolves_intervention_with_prefixed_user_id(self):
        class _FakeInterventionManager:
            def __init__(self):
                self.pending = [
                    {
                        "id": "int-1",
                        "prompt": "Kritik işlem onayı gerekiyor",
                        "options": ["Onayla", "İptal Et"],
                        "context": {"user_id": "telegram:123"},
                        "ts": 1.0,
                    }
                ]
                self.resolved = []
                self.listeners = []

            def register_listener(self, listener):
                self.listeners.append(listener)

            def list_pending(self):
                return list(self.pending)

            def resolve(self, request_id, response):
                self.resolved.append((request_id, response))
                return True

        fake_manager = _FakeInterventionManager()
        mock_ar = AsyncMock()
        mock_ar.route_message = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.get_intervention_manager", lambda: fake_manager)
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router, _ = self._router()
            router.send_outgoing_response = AsyncMock()

            code = router._ensure_intervention_code(fake_manager.pending[0], user_id="123", channel_id="chat-1")
            msg = _make_message(channel_type="telegram", channel_id="chat-1", user_id="123", text=f"onay {code}")
            await router.handle_incoming_message(msg)

            assert fake_manager.resolved == [("int-1", "Onayla")]
            mock_ar.route_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_incoming_message_skips_stale_intervention(self):
        class _FakeInterventionManager:
            def __init__(self):
                self.pending = [
                    {
                        "id": "int-1",
                        "prompt": "Kritik işlem onayı gerekiyor",
                        "options": ["Onayla", "İptal Et"],
                        "context": {"user_id": "123"},
                        "ts": time.time() - 900,
                    }
                ]
                self.resolved = []
                self.listeners = []

            def register_listener(self, listener):
                self.listeners.append(listener)

            def list_pending(self):
                return list(self.pending)

            def resolve(self, request_id, response):
                self.resolved.append((request_id, response))
                return True

        fake_manager = _FakeInterventionManager()
        mock_ar = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.get_intervention_manager", lambda: fake_manager)
            router, mock_agent = self._router()
            mock_ar.route_message = AsyncMock(return_value=mock_agent)
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", channel_id="chat-1", user_id="123", text="onayla")
            await router.handle_incoming_message(msg)

            assert fake_manager.resolved == []
            mock_ar.route_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_incoming_message_skips_unbound_intervention(self):
        class _FakeInterventionManager:
            def __init__(self):
                self.pending = [
                    {
                        "id": "int-1",
                        "prompt": "Kritik işlem onayı gerekiyor",
                        "options": ["Onayla", "İptal Et"],
                        "context": {},
                        "ts": 1.0,
                    }
                ]
                self.resolved = []
                self.listeners = []

            def register_listener(self, listener):
                self.listeners.append(listener)

            def list_pending(self):
                return list(self.pending)

            def resolve(self, request_id, response):
                self.resolved.append((request_id, response))
                return True

        fake_manager = _FakeInterventionManager()
        mock_ar = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.get_intervention_manager", lambda: fake_manager)
            router, mock_agent = self._router()
            mock_ar.route_message = AsyncMock(return_value=mock_agent)
            mp.setattr("core.gateway.router.agent_router", mock_ar)
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", channel_id="chat-1", user_id="123", text="onayla")
            await router.handle_incoming_message(msg)

            assert fake_manager.resolved == []
            mock_ar.route_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_intervention_listener_pushes_prompt_to_last_user_channel(self):
        class _FakeInterventionManager:
            def __init__(self):
                self.listeners = []

            def register_listener(self, listener):
                self.listeners.append(listener)

            def list_pending(self):
                return []

            def resolve(self, request_id, response):
                _ = (request_id, response)
                return True

        fake_manager = _FakeInterventionManager()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.gateway.router.get_intervention_manager", lambda: fake_manager)
            router, _ = self._router()
            router.send_outgoing_response = AsyncMock()

            msg = _make_message(channel_type="telegram", channel_id="chat-22", user_id="22", text="selam")
            router._remember_user_route(msg)

            req = SimpleNamespace(
                id="int-22",
                prompt="Kritik işlem onayı gerekiyor",
                options=["Onayla", "İptal Et"],
                context={"user_id": "22"},
            )
            assert fake_manager.listeners, "listener register edilmedi"

            await fake_manager.listeners[0](req)

            router.send_outgoing_response.assert_awaited_once()
            call = router.send_outgoing_response.await_args_list[0].args
            assert call[0] == "telegram"
            assert call[1] == "chat-22"
            assert "onayla" in call[2].text.lower()
            assert "güvenlik kodu" in call[2].text.lower()
            assert call[2].buttons == []
