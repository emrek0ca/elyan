"""
Unit testler: Gateway kanal adaptörleri
Gerçek ağ bağlantısı gerektirmeyen mock tabanlı testler.
"""
import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from types import SimpleNamespace
from telegram.error import Conflict

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
            "google_chat", "imessage", "sms",
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


class TestTelegramAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.telegram import TelegramAdapter
        cfg = {"token": "test-token", **kwargs}
        return TelegramAdapter(cfg)

    def test_extract_local_image_path_from_absolute_path(self, tmp_path):
        adapter = self._make()
        image_file = tmp_path / "shot.png"
        image_file.write_bytes(b"png")
        text = f"İşlem tamamlandı: {image_file}"
        extracted = adapter._extract_local_image_path(text)
        assert extracted == str(image_file)

    def test_extract_local_image_path_returns_empty_when_not_found(self):
        adapter = self._make()
        extracted = adapter._extract_local_image_path("Ekran görüntüsü alındı.")
        assert extracted == ""

    def test_extract_local_image_path_ignores_url(self):
        adapter = self._make()
        extracted = adapter._extract_local_image_path("Kaynak: https://example.com/image.png")
        assert extracted == ""

    def test_polling_conflict_marks_adapter_unavailable(self):
        adapter = self._make()
        adapter.app = SimpleNamespace(running=True, updater=SimpleNamespace(running=True))
        adapter._is_connected = True

        adapter._handle_polling_error(Conflict("terminated by other getUpdates request"))

        assert adapter.get_status() == "unavailable"
        assert adapter._is_connected is False
        assert adapter._polling_conflict is True

    def test_polling_conflict_schedules_shutdown(self, monkeypatch):
        adapter = self._make()
        adapter.app = SimpleNamespace(running=True, updater=SimpleNamespace(running=True))
        scheduled = []

        class _Loop:
            def create_task(self, coro):
                scheduled.append(coro)
                return SimpleNamespace()

        monkeypatch.setattr("core.gateway.adapters.telegram.asyncio.get_running_loop", lambda: _Loop())

        adapter._handle_polling_error(Conflict("terminated by other getUpdates request"))

        assert scheduled
        for coro in scheduled:
            coro.close()

    @pytest.mark.asyncio
    async def test_connect_deletes_webhook_and_registers_error_callback(self, monkeypatch):
        adapter = self._make()
        updater = SimpleNamespace(start_polling=AsyncMock(), running=True, stop=AsyncMock())
        bot = SimpleNamespace(delete_webhook=AsyncMock())
        app = SimpleNamespace(
            add_handler=MagicMock(),
            initialize=AsyncMock(),
            start=AsyncMock(),
            stop=AsyncMock(),
            shutdown=AsyncMock(),
            updater=updater,
            bot=bot,
            running=True,
        )

        class _Builder:
            def token(self, value):
                _ = value
                return self

            def build(self):
                return app

        monkeypatch.setattr("core.gateway.adapters.telegram.ApplicationBuilder", lambda: _Builder())

        await adapter.connect()

        bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
        updater.start_polling.assert_awaited_once()
        kwargs = updater.start_polling.await_args.kwargs
        assert kwargs["drop_pending_updates"] is True
        assert callable(kwargs["error_callback"])

    @pytest.mark.asyncio
    async def test_handle_photo_ingest_emits_unified_message_with_attachment(self, tmp_path):
        adapter = self._make(inbox_dir=str(tmp_path))
        received = []

        async def _on_message(msg):
            received.append(msg)

        adapter.on_message(_on_message)

        async def _download(dest):
            Path(dest).write_bytes(b"img")

        fake_file = SimpleNamespace(download_to_drive=AsyncMock(side_effect=_download))
        context = SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(return_value=fake_file)))
        photo = SimpleNamespace(file_id="p-1")
        message = SimpleNamespace(message_id=11, photo=[photo], caption="bunu duvar kağıdı yap")
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=42, first_name="Emre"),
            effective_chat=SimpleNamespace(id=1001),
            message=message,
        )

        await adapter._handle_photo(update, context)

        assert len(received) == 1
        assert received[0].attachments
        assert received[0].attachments[0]["type"] == "image"
        assert Path(received[0].attachments[0]["path"]).exists()

    @pytest.mark.asyncio
    async def test_handle_document_ingest_emits_unified_message_with_attachment(self, tmp_path):
        adapter = self._make(inbox_dir=str(tmp_path))
        received = []

        async def _on_message(msg):
            received.append(msg)

        adapter.on_message(_on_message)

        async def _download(dest):
            Path(dest).write_bytes(b"doc")

        fake_file = SimpleNamespace(download_to_drive=AsyncMock(side_effect=_download))
        context = SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(return_value=fake_file)))
        doc = SimpleNamespace(file_id="d-1", file_name="report.pdf", mime_type="application/pdf", file_size=16)
        message = SimpleNamespace(message_id=12, document=doc, caption="")
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=42, first_name="Emre"),
            effective_chat=SimpleNamespace(id=1001),
            message=message,
        )

        await adapter._handle_document(update, context)

        assert len(received) == 1
        assert received[0].attachments
        assert received[0].attachments[0]["type"] == "document"
        assert Path(received[0].attachments[0]["path"]).exists()

    @pytest.mark.asyncio
    async def test_send_message_auto_sends_document_from_text(self, tmp_path):
        adapter = self._make(auto_send_paths_from_text=True)
        adapter.app = MagicMock()
        adapter.app.bot = AsyncMock()

        doc = tmp_path / "report.docx"
        doc.write_bytes(b"doc")
        response = UnifiedResponse(text=f"Belge hazır: {doc}")

        await adapter.send_message("123", response)

        adapter.app.bot.send_document.assert_awaited_once()
        assert adapter.app.bot.send_photo.await_count == 0
        assert adapter.app.bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_send_message_does_not_auto_send_document_from_text_by_default(self, tmp_path):
        adapter = self._make()
        adapter.app = MagicMock()
        adapter.app.bot = AsyncMock()

        doc = tmp_path / "report.docx"
        doc.write_bytes(b"doc")
        response = UnifiedResponse(text=f"Belge hazır: {doc}")

        await adapter.send_message("123", response)

        adapter.app.bot.send_document.assert_not_called()
        adapter.app.bot.send_photo.assert_not_called()
        adapter.app.bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_renders_inline_buttons(self):
        adapter = self._make()
        adapter.app = MagicMock()
        adapter.app.bot = AsyncMock()

        response = UnifiedResponse(
            text="Onay gerekiyor",
            buttons=[
                {"text": "Onayla", "callback_data": "intervention:req1:approve", "row": 0},
                {"text": "Reddet", "callback_data": "intervention:req1:deny", "row": 0},
            ],
        )
        await adapter.send_message("123", response)

        adapter.app.bot.send_message.assert_awaited_once()
        kwargs = adapter.app.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == "123"
        assert kwargs["text"] == "Onay gerekiyor"
        assert kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_intervention_callback_oversize_compacted_and_resolved(self, monkeypatch):
        adapter = self._make()

        long_req = "req_" + ("x" * 120)
        markup = adapter._build_reply_markup(
            [{"text": "Onayla", "callback_data": f"intervention:{long_req}:approve", "row": 0}]
        )
        assert markup is not None
        compact_data = markup.inline_keyboard[0][0].callback_data
        assert len(compact_data.encode("utf-8")) <= 64

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": long_req, "context": {"user_id": "42"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data=compact_data,
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )
        await adapter._handle_callback_query(update, None)
        assert fake._resolved == [(long_req, "Onayla")]

    @pytest.mark.asyncio
    async def test_callback_query_intervention_resolves_pending_request(self, monkeypatch):
        adapter = self._make()
        adapter.app = MagicMock()
        adapter.app.bot = AsyncMock()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "req55", "context": {"user_id": "42"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:req55:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == [("req55", "Onayla")]
        query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_query_task_command_emits_unified_message(self):
        adapter = self._make()
        received = []

        async def _on_message(msg):
            received.append(msg)

        adapter.on_message(_on_message)

        query = SimpleNamespace(
            id="cb-task-1",
            data="task|cancel|away_123",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert len(received) == 1
        assert received[0].text == "away_123 iptal et"
        assert received[0].metadata["source"] == "telegram_callback"

    @pytest.mark.asyncio
    async def test_callback_query_intervention_rejects_other_user(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "req55", "context": {"user_id": "99"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:req55:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == []
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_fallbacks_to_latest_user_pending(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [
                    {"id": "old01", "ts": 10, "context": {"user_id": "42"}},
                    {"id": "new99", "ts": 20, "context": {"user_id": "42"}},
                ]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        # request_id intentionally unknown => should fallback to latest user pending (new99)
        query = SimpleNamespace(
            id="cb-1",
            data="intervention:missing01:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == [("new99", "Onayla")]
        query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_uses_from_user_when_effective_missing(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "req55", "context": {"user_id": "42"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:req55:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=None,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == [("req55", "Onayla")]
        query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_accepts_prefixed_user_id(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "req55", "context": {"user_id": "telegram:42"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:req55:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == [("req55", "Onayla")]
        query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_rejects_stale_request(self, monkeypatch):
        adapter = self._make(callback_stale_seconds=60)

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "req55", "ts": time.time() - 600, "context": {"user_id": "42"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:req55:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == []
        query.answer.assert_awaited()
        query.edit_message_text.assert_awaited_once()
        assert "süresi dolmuş" in query.edit_message_text.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_fallback_requires_binding(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "free1", "ts": 10, "context": {}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:missing01:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == []
        query.edit_message_text.assert_awaited_once()
        assert "geçerli değil" in query.edit_message_text.await_args.args[0].lower()

    @pytest.mark.asyncio
    async def test_callback_query_intervention_fallback_uses_channel_binding(self, monkeypatch):
        adapter = self._make()

        class _FakeManager:
            def __init__(self):
                self._resolved = []

            def list_pending(self):
                return [{"id": "chat-bound", "ts": 10, "context": {"channel": "telegram", "channel_id": "777"}}]

            def resolve(self, request_id, decision):
                self._resolved.append((request_id, decision))
                return True

        fake = _FakeManager()
        monkeypatch.setattr("core.gateway.adapters.telegram.get_intervention_manager", lambda: fake)

        query = SimpleNamespace(
            id="cb-1",
            data="intervention:missing01:approve",
            from_user=SimpleNamespace(id=42, first_name="Emre"),
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=query.from_user,
            effective_chat=SimpleNamespace(id=777),
        )

        await adapter._handle_callback_query(update, None)

        assert fake._resolved == [("chat-bound", "Onayla")]
        query.edit_message_text.assert_awaited_once()

    def test_parse_intervention_callback_supports_pipe_and_suffix(self):
        from core.gateway.adapters.telegram import TelegramAdapter

        parsed = TelegramAdapter._parse_intervention_callback("INTERVENTION|req77|approve:v2")
        assert parsed == ("req77", True)

        parsed2 = TelegramAdapter._parse_intervention_callback("intervention:req88:deny|meta")
        assert parsed2 == ("req88", False)


class TestWhatsAppAdapter:
    def _make(self, **kwargs):
        from core.gateway.adapters.whatsapp import WhatsAppAdapter
        cfg = {
            "id": "whatsapp",
            "bridge_url": "http://127.0.0.1:18792",
            "bridge_token": "tok",
            "auto_start_bridge": False,
            **kwargs,
        }
        return WhatsAppAdapter(cfg)

    @pytest.mark.asyncio
    async def test_connect_ready_state(self, monkeypatch):
        adapter = self._make()

        monkeypatch.setattr(adapter, "_get_bridge_state", AsyncMock(return_value={"ready": True}))

        async def _dummy_poll():
            await asyncio.sleep(0.01)

        monkeypatch.setattr(adapter, "_poll_incoming_loop", _dummy_poll)
        await adapter.connect()
        assert adapter.get_status() == "connected"
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_connect_not_ready_raises(self, monkeypatch):
        adapter = self._make()
        monkeypatch.setattr(adapter, "_get_bridge_state", AsyncMock(return_value={"ready": False}))
        with pytest.raises(RuntimeError):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_send_message_posts_to_bridge(self, monkeypatch):
        adapter = self._make()
        adapter._is_connected = True
        bridge_call = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(adapter, "_bridge_call", bridge_call)

        await adapter.send_message("905551112233", UnifiedResponse(text="Merhaba"))
        bridge_call.assert_awaited_once()
        kwargs = bridge_call.await_args.kwargs
        assert kwargs["path"] == "/send"
        assert kwargs["payload"]["to"] == "905551112233"

    @pytest.mark.asyncio
    async def test_send_message_bridge_media_when_file_present(self, monkeypatch, tmp_path):
        adapter = self._make()
        adapter._is_connected = True
        bridge_call = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(adapter, "_bridge_call", bridge_call)

        report = tmp_path / "daily_report.pdf"
        report.write_bytes(b"pdf")

        await adapter.send_message("905551112233", UnifiedResponse(text=f"Rapor hazır: {report}"))

        called_paths = [c.kwargs.get("path") for c in bridge_call.await_args_list]
        assert "/send-media" in called_paths

    @pytest.mark.asyncio
    async def test_cloud_send_media_document_payload(self, monkeypatch, tmp_path):
        from core.gateway.adapters.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter(
            {
                "type": "whatsapp",
                "mode": "cloud",
                "phone_number_id": "123456",
                "access_token": "token",
                "verify_token": "verify-me",
            }
        )
        upload_mock = AsyncMock(return_value="media-123")
        payload_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(adapter, "_upload_cloud_media", upload_mock)
        monkeypatch.setattr(adapter, "_send_cloud_payload", payload_mock)

        doc = tmp_path / "ops.xlsx"
        doc.write_bytes(b"xlsx")

        await adapter._send_cloud_media("905551112233", str(doc), caption="Rapor")
        payload = payload_mock.await_args.args[0]
        assert payload["type"] == "document"
        assert payload["document"]["id"] == "media-123"
        assert payload["document"]["filename"] == "ops.xlsx"

    @pytest.mark.asyncio
    async def test_poll_incoming_maps_message(self, monkeypatch):
        adapter = self._make()
        received = []

        async def _on_message(msg):
            received.append(msg)
            adapter._is_connected = False

        adapter.on_message(_on_message)
        adapter._is_connected = True

        monkeypatch.setattr(
            adapter,
            "_bridge_call",
            AsyncMock(
                return_value={
                    "items": [
                        {
                            "id": "m1",
                            "from": "905551112233@c.us",
                            "body": "Selam",
                            "type": "chat",
                            "timestamp": 1700000000,
                            "pushName": "Emre",
                            "isGroup": False,
                        }
                    ]
                }
            ),
        )
        await adapter._poll_incoming_loop()
        assert len(received) == 1
        assert received[0].channel_type == "whatsapp"
        assert received[0].text == "Selam"

    @pytest.mark.asyncio
    async def test_cloud_connect_requires_credentials(self):
        from core.gateway.adapters.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter({"type": "whatsapp", "mode": "cloud"})
        with pytest.raises(RuntimeError):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_cloud_webhook_verification_success(self):
        from aiohttp.test_utils import make_mocked_request
        from core.gateway.adapters.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter(
            {
                "type": "whatsapp",
                "mode": "cloud",
                "phone_number_id": "123456",
                "access_token": "token",
                "verify_token": "verify-me",
            }
        )
        req = make_mocked_request(
            "GET",
            "/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=ok123",
        )
        resp = await adapter.handle_webhook_verification(req)
        assert resp.status == 200
        assert resp.text == "ok123"

    @pytest.mark.asyncio
    async def test_cloud_webhook_maps_incoming_text(self):
        from aiohttp.test_utils import make_mocked_request
        from core.gateway.adapters.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter(
            {
                "type": "whatsapp",
                "mode": "cloud",
                "phone_number_id": "123456",
                "access_token": "token",
                "verify_token": "verify-me",
            }
        )
        got = []

        async def _on_message(msg):
            got.append(msg)

        adapter.on_message(_on_message)

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "905551112233", "profile": {"name": "Emre"}}],
                                "messages": [
                                    {
                                        "id": "wamid-1",
                                        "from": "905551112233",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "Selam Elyan"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        req = make_mocked_request("POST", "/whatsapp/webhook")
        req._post = None
        req._read_bytes = json.dumps(payload).encode("utf-8")
        req.json = AsyncMock(return_value=payload)

        resp = await adapter.handle_webhook(req)
        assert resp.status == 200
        assert len(got) == 1
        assert got[0].channel_type == "whatsapp"
        assert got[0].user_id == "905551112233"
        assert got[0].text == "Selam Elyan"


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

    @pytest.mark.asyncio
    async def test_send_webhook_appends_fallback_attachment_text(self):
        adapter = self._make()
        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        adapter._session = mock_session

        await adapter.send_message(
            "spaces/abc123",
            UnifiedResponse(text="Test", metadata={"fallback_text": "Dosyalar:\n- report.docx"}),
        )
        payload = mock_session.post.call_args[1]["json"]
        assert "report.docx" in payload["text"]


class TestSlackAdapter:
    @pytest.mark.asyncio
    async def test_send_message_uploads_attachments(self, tmp_path):
        pytest.importorskip("slack_bolt")
        from core.gateway.adapters.slack import SlackAdapter

        adapter = SlackAdapter({"app_token": "xapp-1", "bot_token": "xoxb-1"})
        fake_client = AsyncMock()
        adapter.app = SimpleNamespace(client=fake_client)
        doc = tmp_path / "report.docx"
        doc.write_bytes(b"doc")

        await adapter.send_message(
            "C123",
            UnifiedResponse(text="Rapor hazir", attachments=[{"path": str(doc), "name": "report.docx", "type": "file"}]),
        )

        fake_client.chat_postMessage.assert_awaited_once()
        fake_client.files_upload_v2.assert_awaited_once()


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
