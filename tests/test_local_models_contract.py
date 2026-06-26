from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from runtime import local_models


def test_ollama_status_separates_configured_and_reachable(monkeypatch) -> None:
    client = local_models.OllamaClient(default_model="llama3.2:3b")

    def fake_get(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    fake_requests = SimpleNamespace(
        get=fake_get,
        post=lambda *_args, **_kwargs: None,
        RequestException=requests.RequestException,
        Timeout=requests.Timeout,
        ConnectionError=requests.ConnectionError,
    )
    monkeypatch.setattr(local_models, "_requests_module", lambda: fake_requests)

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

    fake_requests = SimpleNamespace(
        get=lambda *_args, **_kwargs: None,
        post=fake_post,
        RequestException=requests.RequestException,
        Timeout=requests.Timeout,
        ConnectionError=requests.ConnectionError,
    )
    monkeypatch.setattr(local_models, "_requests_module", lambda: fake_requests)

    result = client.chat("local-model", [{"role": "user", "content": "merhaba"}])

    assert result["ok"] is False
    assert result["error"] == "request_timeout"


def test_ollama_chat_falls_back_to_installed_model(monkeypatch) -> None:
    client = local_models.OllamaClient(default_model="llama3.1:8b")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, *, ok: bool, payload: dict[str, object]):
            self.ok = ok
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_get(_url: str, timeout: float = 0) -> FakeResponse:
        assert timeout > 0
        return FakeResponse(ok=True, payload={"models": [{"name": "llama3.2:3b"}, {"name": "llama3.2:latest"}]})

    def fake_post(_url: str, *, json: dict[str, object], timeout: float = 0) -> FakeResponse:
        captured["model"] = json["model"]
        captured["messages"] = json["messages"]
        captured["timeout"] = timeout
        return FakeResponse(ok=True, payload={"message": {"content": "selam"}})

    fake_requests = SimpleNamespace(
        get=fake_get,
        post=fake_post,
        RequestException=requests.RequestException,
        Timeout=requests.Timeout,
        ConnectionError=requests.ConnectionError,
    )
    monkeypatch.setattr(local_models, "_requests_module", lambda: fake_requests)

    result = client.chat("llama3.1:8b", [{"role": "user", "content": "merhaba"}])

    assert result["ok"] is True
    assert result["content"] == "selam"
    assert captured["model"] == "llama3.2:3b"
