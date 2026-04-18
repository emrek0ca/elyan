from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.decision_fabric import Decision
from core.gateway import server as gateway_server


class _Request:
    def __init__(self, *, method: str, data: dict | None = None, query: dict[str, str] | None = None) -> None:
        self.method = method
        self._data = data or {}
        self.rel_url = SimpleNamespace(query=query or {})
        self.match_info = {}
        self.headers = {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None

    async def json(self):
        return self._data


class _FakeDecisionFabric:
    def __init__(self) -> None:
        self.recorded: list[Decision] = []
        self.search_calls: list[tuple[str, str, int]] = []

    def search(self, query: str, workspace_id: str, *, limit: int = 20):
        self.search_calls.append((query, workspace_id, limit))
        return [
            Decision(
                id="decision-1",
                summary="Iyzico checkout akisi korundu",
                context="Webhook imzasi compare_digest ile dogrulandi",
                actor_id="actor-1",
                workspace_id=workspace_id,
                tags=["billing", "security"],
            )
        ]

    def record(self, decision: Decision) -> str:
        self.recorded.append(decision)
        return "decision-2"


@pytest.mark.asyncio
async def test_request_requires_user_session_covers_decision_fabric_path() -> None:
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    request = _Request(method="GET", query={})
    request.path = "/api/v1/decision-fabric"

    assert srv._request_requires_user_session(request) is True


@pytest.mark.asyncio
async def test_v1_decision_fabric_get_searches_by_workspace(monkeypatch) -> None:
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    session = {"session_id": "s-1", "workspace_id": "workspace-a", "user_id": "user-1"}
    fake_fabric = _FakeDecisionFabric()

    monkeypatch.setattr(
        gateway_server.ElyanGatewayServer,
        "_require_user_session",
        lambda self, request, allow_cookie=True: (True, "", dict(session)),
    )
    monkeypatch.setattr(gateway_server, "get_decision_fabric", lambda: fake_fabric)

    request = _Request(method="GET", query={"query": "checkout", "limit": "3"})
    response = await gateway_server.ElyanGatewayServer.handle_v1_decision_fabric(srv, request)

    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["ok"] is True
    assert payload["query"] == "checkout"
    assert payload["workspace_id"] == "workspace-a"
    assert payload["count"] == 1
    assert payload["results"][0]["summary"] == "Iyzico checkout akisi korundu"
    assert fake_fabric.search_calls == [("checkout", "workspace-a", 3)]


@pytest.mark.asyncio
async def test_v1_decision_fabric_post_records_decision(monkeypatch) -> None:
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    session = {"session_id": "s-1", "workspace_id": "workspace-a", "user_id": "user-1"}
    fake_fabric = _FakeDecisionFabric()

    monkeypatch.setattr(
        gateway_server.ElyanGatewayServer,
        "_require_user_session",
        lambda self, request, allow_cookie=True: (True, "", dict(session)),
    )
    monkeypatch.setattr(gateway_server, "get_decision_fabric", lambda: fake_fabric)

    request = _Request(
        method="POST",
        data={
            "summary": "Logo connector secildi",
            "context": "Muhasebe ekibi mevcut lisans kullaniyor",
            "tags": ["logo", "accounting"],
            "related_event_ids": ["evt-1"],
            "metadata": {"source": "api"},
        },
    )
    response = await gateway_server.ElyanGatewayServer.handle_v1_decision_fabric(srv, request)

    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["ok"] is True
    assert payload["decision_id"] == "decision-2"
    assert payload["decision"]["summary"] == "Logo connector secildi"
    assert fake_fabric.recorded[0].workspace_id == "workspace-a"
    assert fake_fabric.recorded[0].actor_id == "user-1"
