from __future__ import annotations

import base64
from pathlib import Path

import pytest

from tools import vision_tools


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return dict(self._payload)


@pytest.mark.asyncio
async def test_ollama_vision_missing_model_fails_fast_without_pull(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(url)
            return _FakeResponse(404, {})

    monkeypatch.setattr(vision_tools, "VISION_AUTO_PULL", False)
    monkeypatch.setattr(vision_tools, "_ensure_ollama_runtime", lambda: True)
    monkeypatch.setattr("tools.vision_tools.httpx.AsyncClient", lambda timeout=0: _FakeClient())

    image_path = tmp_path / "shot.png"
    image_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aA1EAAAAASUVORK5CYII="))

    result = await vision_tools.analyze_image(str(image_path), prompt="ekrani ozetle")
    assert result["success"] is False
    assert result["error_code"] == "vision_model_missing"
    assert len(calls) == 1
    assert "/api/pull" not in calls[0]
