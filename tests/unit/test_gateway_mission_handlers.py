import json
from types import SimpleNamespace

import pytest

from core.gateway import server as gateway_server
from core.mission_control import MissionRuntime


class _Req:
    def __init__(self, data=None, query=None, match_info=None):
        self._data = data or {}
        self.query = query or {}
        self.rel_url = SimpleNamespace(query=self.query)
        self.match_info = match_info or {}
        self.headers = {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None

    async def json(self):
        return self._data


class _DummyAgent:
    async def process_envelope(self, text, channel="dashboard", metadata=None, attachments=None):
        _ = (text, channel, metadata, attachments)
        from core.contracts.agent_response import AgentResponse

        return AgentResponse(
            run_id="run_mission",
            text="Tamamlanan node çıktısı.",
            evidence_manifest_path="/tmp/evidence.json",
            status="success",
        )


@pytest.mark.asyncio
async def test_handle_missions_create_and_list(tmp_path, monkeypatch):
    runtime = MissionRuntime(storage_dir=tmp_path)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _DummyAgent()
    srv.mission_runtime = runtime

    create_resp = await gateway_server.ElyanGatewayServer.handle_missions_create(
        srv,
        _Req({"goal": "Kısa rapor hazırla", "mode": "Balanced", "user_id": "local", "channel": "dashboard"}),
    )
    create_payload = json.loads(create_resp.text)
    assert create_payload["ok"] is True
    mission_id = create_payload["mission"]["mission_id"]

    list_resp = await gateway_server.ElyanGatewayServer.handle_missions_list(
        srv,
        _Req(query={"user_id": "local", "limit": "10"}),
    )
    list_payload = json.loads(list_resp.text)
    assert list_payload["ok"] is True
    assert any(item["mission_id"] == mission_id for item in list_payload["missions"])


@pytest.mark.asyncio
async def test_handle_mission_detail_and_skill_save(tmp_path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()
    mission = await runtime.create_mission("Landing page üret", agent=agent, auto_start=False)
    await runtime.run_mission(mission.mission_id, agent=agent)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = agent
    srv.mission_runtime = runtime

    detail_resp = await gateway_server.ElyanGatewayServer.handle_mission_detail(
        srv,
        _Req(match_info={"mission_id": mission.mission_id}),
    )
    detail_payload = json.loads(detail_resp.text)
    assert detail_payload["ok"] is True
    assert detail_payload["mission"]["mission_id"] == mission.mission_id

    skill_resp = await gateway_server.ElyanGatewayServer.handle_missions_skill_save(
        srv,
        _Req({"mission_id": mission.mission_id}),
    )
    skill_payload = json.loads(skill_resp.text)
    assert skill_payload["ok"] is True
    assert skill_payload["skill"]["source_mission_id"] == mission.mission_id


@pytest.mark.asyncio
async def test_handle_missions_approval_resolve(tmp_path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()
    mission = await runtime.create_mission("Production deploy yayınla", agent=agent, auto_start=False)
    await runtime.run_mission(mission.mission_id, agent=agent)
    pending = runtime.pending_approvals(owner="local")
    assert pending

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = agent
    srv.mission_runtime = runtime

    resp = await gateway_server.ElyanGatewayServer.handle_missions_approval_resolve(
        srv,
        _Req({"id": pending[0]["approval_id"], "approved": True}),
    )
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["mission"]["mission_id"] == mission.mission_id


@pytest.mark.asyncio
async def test_handle_create_task_routes_to_mission_runtime(tmp_path, monkeypatch):
    runtime = MissionRuntime(storage_dir=tmp_path)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _DummyAgent()
    srv.mission_runtime = runtime

    resp = await gateway_server.ElyanGatewayServer.handle_create_task(
        srv,
        _Req({"text": "Landing page üret", "channel": "dashboard", "mode": "Balanced", "user_id": "local"}),
    )
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["status"] == "mission_created"
    assert payload["mission"]["goal"] == "Landing page üret"
    assert runtime.list_missions(owner="local", limit=5)[0]["mission_id"] == payload["mission"]["mission_id"]
