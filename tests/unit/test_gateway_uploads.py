from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from core.gateway import server as gateway_server


async def _build_upload_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gateway_server, "resolve_elyan_data_dir", lambda: tmp_path)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *args, **kwargs: None)

    scheduled_coroutines = []

    def _capture_task(coro):
        scheduled_coroutines.append(coro)
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(gateway_server.asyncio, "create_task", _capture_task)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = SimpleNamespace(process=lambda prompt: asyncio.sleep(0))

    app = web.Application()

    async def _handler(request):
        return await gateway_server.ElyanGatewayServer.handle_file_upload(srv, request)

    app.router.add_post("/api/upload", _handler)

    client = TestClient(TestServer(app))
    await client.start_server()
    return client, scheduled_coroutines


@pytest.mark.asyncio
async def test_file_upload_rejects_unsupported_mime(monkeypatch, tmp_path):
    client, _ = await _build_upload_client(monkeypatch, tmp_path)
    monkeypatch.setattr(gateway_server, "_UPLOAD_ALLOWED_MIME_TYPES", {"text/plain"})
    try:
        form = FormData()
        form.add_field("file", b"binary", filename="payload.bin", content_type="application/octet-stream")

        response = await client.post("/api/upload", data=form)
        payload = await response.json()

        assert response.status == 415
        assert payload["ok"] is False
        assert "unsupported file type" in str(payload["error"]).lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_file_upload_rejects_payloads_over_limit(monkeypatch, tmp_path):
    client, _ = await _build_upload_client(monkeypatch, tmp_path)
    monkeypatch.setattr(gateway_server, "_UPLOAD_MAX_BYTES", 4)
    try:
        form = FormData()
        form.add_field("file", b"12345", filename="note.txt", content_type="text/plain")

        response = await client.post("/api/upload", data=form)
        payload = await response.json()

        assert response.status == 413
        assert payload["ok"] is False
        assert "too large" in str(payload["error"]).lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_file_upload_sanitizes_filename_and_keeps_path_inside_upload_dir(monkeypatch, tmp_path):
    client, scheduled_coroutines = await _build_upload_client(monkeypatch, tmp_path)
    try:
        form = FormData()
        form.add_field("file", b"hello world", filename="../danger?.txt", content_type="text/plain")

        response = await client.post("/api/upload", data=form)
        payload = await response.json()

        assert response.status == 200
        assert payload["ok"] is True
        assert payload["filename"] == "danger_.txt"

        saved_path = Path(payload["path"]).resolve()
        upload_root = (tmp_path / "uploads").resolve()
        assert saved_path.parent == upload_root
        assert saved_path.read_bytes() == b"hello world"
        assert len(scheduled_coroutines) == 1
    finally:
        await client.close()
