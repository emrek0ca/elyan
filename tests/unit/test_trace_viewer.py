import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from core.gateway import server as gateway_server
from core.mission_control import MissionRuntime
from elyan.verifier import evidence as trace_evidence


class _Req:
    def __init__(self, *, match_info=None, query=None):
        self.match_info = match_info or {}
        self.query = query or {}
        self.rel_url = SimpleNamespace(query=self.query)
        self.headers = {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None


@pytest.mark.asyncio
async def test_trace_bundle_includes_attachment_evidence(tmp_path, monkeypatch):
    data_dir = tmp_path / "elyan-data"
    monkeypatch.setenv("ELYAN_DATA_DIR", str(data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    runtime = MissionRuntime(storage_dir=tmp_path / "missions")
    attachment = data_dir / "evidence.txt"
    attachment.write_text("proof", encoding="utf-8")

    mission = await runtime.create_mission("Trace viewer testi", auto_start=False, attachments=[str(attachment)])
    bundle = trace_evidence.build_trace_bundle(mission.mission_id, runtime=runtime)

    assert bundle["ok"] is True
    assert bundle["history"]["mission_id"] == mission.mission_id
    assert bundle["evidence"]
    assert bundle["evidence"][0]["url"].startswith("/api/evidence/file?path=")


@pytest.mark.asyncio
async def test_gateway_trace_handlers_render_and_serve_evidence(tmp_path, monkeypatch):
    data_dir = tmp_path / "elyan-data"
    monkeypatch.setenv("ELYAN_DATA_DIR", str(data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    runtime = MissionRuntime(storage_dir=tmp_path / "missions")
    attachment = data_dir / "trace-artifact.png"
    attachment.write_bytes(b"fake-image-bytes")

    mission = await runtime.create_mission("Yatirimci trace testi", auto_start=False, attachments=[str(attachment)])

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.mission_runtime = runtime

    api_resp = await gateway_server.ElyanGatewayServer.handle_trace_api(
        srv,
        _Req(match_info={"task_id": mission.mission_id}),
    )
    api_payload = json.loads(api_resp.text)
    assert api_payload["ok"] is True
    assert api_payload["trace"]["task_id"] == mission.mission_id
    assert api_payload["trace"]["evidence"]

    page_resp = await gateway_server.ElyanGatewayServer.handle_trace_page(
        srv,
        _Req(match_info={"task_id": mission.mission_id}),
    )
    assert mission.goal in page_resp.text
    assert "Trace Viewer" in page_resp.text

    file_resp = await gateway_server.ElyanGatewayServer.handle_evidence_file_get(
        srv,
        _Req(query={"path": api_payload["trace"]["evidence"][0]["path"]}),
    )
    assert isinstance(file_resp, web.FileResponse)
