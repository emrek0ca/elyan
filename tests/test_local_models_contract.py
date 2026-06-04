from __future__ import annotations

import requests

from runtime import local_models


def test_ollama_status_separates_configured_and_reachable(monkeypatch) -> None:
    client = local_models.OllamaClient(default_model="llama3.2:3b")

    def fake_get(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(local_models.requests, "get", fake_get)

    status = client.status()

    assert status["configured"] is True
    assert status["reachable"] is False
    assert status["available"] is False
    assert status["errorCode"] == "provider_unreachable"
    assert status["lastCheckedAt"]


def test_openai_compatible_chat_normalizes_timeout(monkeypatch) -> None:
    client = local_models.LMStudioClient(default_model="local-model")

    def fake_post(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(local_models.requests, "post", fake_post)

    result = client.chat("local-model", [{"role": "user", "content": "merhaba"}])

    assert result["ok"] is False
    assert result["error"] == "request_timeout"
