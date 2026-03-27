from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.contracts.agent_response import AgentResponse, AttachmentRef
from core.mission_control import MissionRuntime


class _DummyAgent:
    def __init__(self, response_metadata: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.response_metadata = dict(response_metadata or {})

    async def process_envelope(self, text, channel="dashboard", metadata=None, attachments=None):
        self.calls.append(
            {
                "text": text,
                "channel": channel,
                "metadata": metadata or {},
                "attachments": attachments or [],
            }
        )
        return AgentResponse(
            run_id="run_test_1",
            text="Somut çıktı üretildi.",
            attachments=[AttachmentRef(path="/tmp/output.txt", type="file", name="output.txt")],
            evidence_manifest_path="/tmp/evidence.json",
            status="success",
            metadata=dict(self.response_metadata),
        )


class _NoArtifactAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def process_envelope(self, text, channel="dashboard", metadata=None, attachments=None):
        self.calls.append(
            {
                "text": text,
                "channel": channel,
                "metadata": metadata or {},
                "attachments": attachments or [],
            }
        )
        return AgentResponse(
            run_id="run_test_2",
            text="Yapabileceklerim: dosya islemleri ve arastirma.",
            evidence_manifest_path="/tmp/evidence.json",
            status="success",
        )


class _DirectIntentAgent(_NoArtifactAgent):
    def __init__(self) -> None:
        super().__init__()
        self.intent_parser = object()
        self._last_direct_intent_payload = {}

    def _should_run_direct_intent(self, intent, user_input):
        _ = user_input
        return isinstance(intent, dict) and str(intent.get("action") or "").strip() in {"write_file", "read_file"}

    async def _run_direct_intent(self, intent, user_input, role, history, user_id="local"):
        _ = (user_input, role, history, user_id)
        self.calls.append({"direct_intent": intent})
        path = str(intent.get("params", {}).get("path") or "")
        self._last_direct_intent_payload = {"success": True, "path": path}
        return f"Dosya işlendi: {path}"


class _BrowserDirectIntentAgent:
    def __init__(self) -> None:
        self.intent_parser = object()
        self._last_direct_intent_payload = {}
        self.shot_calls = 0

    async def process_envelope(self, text, channel="dashboard", metadata=None, attachments=None):
        _ = (text, channel, metadata, attachments)
        raise AssertionError("direct intent path should be used")

    def _should_run_direct_intent(self, intent, user_input):
        _ = user_input
        return isinstance(intent, dict) and str(intent.get("action") or "").strip() == "open_url"

    async def _run_direct_intent(self, intent, user_input, role, history, user_id="local"):
        _ = (intent, user_input, role, history, user_id)
        self._last_direct_intent_payload = {"success": True, "url": "https://openai.com"}
        return "İşlem tamamlandı: https://openai.com"

    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = (params, kwargs)
        assert tool_name == "take_screenshot"
        self.shot_calls += 1
        return {"success": True, "path": "/tmp/browser-proof.png"}


class _BrowserSearchDirectIntentAgent(_BrowserDirectIntentAgent):
    def __init__(self) -> None:
        super().__init__()
        self.direct_intents: list[dict] = []

    async def _run_direct_intent(self, intent, user_input, role, history, user_id="local"):
        _ = (user_input, role, history, user_id)
        self.direct_intents.append(dict(intent))
        url = str(intent.get("params", {}).get("url") or "")
        self._last_direct_intent_payload = {"success": True, "url": url}
        return f"İşlem tamamlandı: {url}"


class _FilePathDirectIntentAgent(_NoArtifactAgent):
    def __init__(self) -> None:
        super().__init__()
        self.intent_parser = object()
        self._last_direct_intent_payload = {}

    def _should_run_direct_intent(self, intent, user_input):
        _ = user_input
        return isinstance(intent, dict) and str(intent.get("action") or "").strip() == "write_file"

    async def _run_direct_intent(self, intent, user_input, role, history, user_id="local"):
        _ = (intent, user_input, role, history, user_id)
        self._last_direct_intent_payload = {
            "success": True,
            "file_path": "/tmp/direct-file-note.txt",
        }
        return "Dosya yazildi: /tmp/direct-file-note.txt"


@pytest.mark.asyncio
async def test_create_mission_builds_parallel_graph_for_code_task(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "Bu repo için feature geliştir ve doğrula",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    node_ids = [node.node_id for node in mission.graph.nodes]
    assert mission.route_mode == "code"
    assert node_ids[0] == "planner"
    assert "verifier" in node_ids
    assert "delivery" in node_ids
    assert mission.graph.parallel_waves
    assert any(node.specialist == "code" for node in mission.graph.nodes)


@pytest.mark.asyncio
async def test_create_mission_routes_landing_page_to_code(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "landing page üret html olarak kaydet",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    assert mission.route_mode == "code"
    assert mission.success_contract["route_mode"] == "code"
    assert any(node.specialist == "code" for node in mission.graph.nodes)


@pytest.mark.asyncio
async def test_create_mission_routes_spreadsheet_request_to_data(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "excel tablo hazırla ve csv olarak da ver",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    assert mission.route_mode == "data"
    assert mission.success_contract["route_mode"] == "data"
    assert any(node.specialist == "data" for node in mission.graph.nodes)


@pytest.mark.asyncio
async def test_create_mission_routes_file_request_to_file_and_sequences_steps(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "Masaüstüne test_elyan_note.txt dosyasına 'Merhaba Elyan' yaz ve sonra içeriğini doğrula",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    assert mission.route_mode == "file"
    work_nodes = [node for node in mission.graph.nodes if node.node_id.startswith("step_")]
    assert [node.specialist for node in work_nodes] == ["file", "file"]
    assert work_nodes[0].depends_on == ["planner"]
    assert work_nodes[1].depends_on == [work_nodes[0].node_id]
    snapshot = runtime.sync_store.get_user_snapshot("local")
    assert snapshot["requests"][0]["request_id"] == mission.mission_id
    assert snapshot["requests"][0]["request_class"] == "direct_action"


@pytest.mark.asyncio
async def test_create_mission_routes_python_file_request_to_code(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "Python ile tek dosyalık basit bir hesap makinesi yaz ve masaüstüne calc_app.py olarak kaydet",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    assert mission.route_mode == "code"
    assert any(node.specialist == "code" for node in mission.graph.nodes)


@pytest.mark.asyncio
async def test_run_mission_collects_evidence_and_deliverable(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()

    mission = await runtime.create_mission(
        "Rakip analizi yap ve kısa rapor hazırla",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "completed"
    assert mission.deliverable
    assert mission.evidence
    assert any(record.kind == "manifest" for record in mission.evidence)
    assert any(node.specialist == "verifier" and node.status == "completed" for node in mission.graph.nodes)
    assert agent.calls


@pytest.mark.asyncio
async def test_file_node_requires_concrete_artifact_and_uses_raw_objective(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _NoArtifactAgent()

    mission = await runtime.create_mission(
        "Masaüstüne note.txt yaz ve sonra doğrula",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "failed"
    assert agent.calls
    assert agent.calls[0]["text"] == "Masaüstüne note.txt yaz"
    work_nodes = [node for node in mission.graph.nodes if node.node_id.startswith("step_")]
    assert work_nodes[0].status == "failed"
    assert any("Somut artifact üretilmedi" in (event.label or "") for event in mission.events)


@pytest.mark.asyncio
async def test_file_node_prefers_direct_intent_with_inferred_path(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DirectIntentAgent()

    mission = await runtime.create_mission(
        "Masaüstüne note.txt dosyasına 'Merhaba Elyan' yaz ve sonra içeriğini doğrula",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert any("direct_intent" in call for call in agent.calls)
    first_direct = next(call["direct_intent"] for call in agent.calls if "direct_intent" in call)
    assert first_direct["action"] == "write_file"
    assert first_direct["params"]["path"] == "~/Desktop/note.txt"


@pytest.mark.asyncio
async def test_plan_first_and_per_step_approval_shape_mission_graph(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)

    mission = await runtime.create_mission(
        "Masaüstüne note.txt dosyasına 'Merhaba Elyan' yaz ama önce planla ve sorarak ilerle",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    assert mission.success_contract["requires_plan"] is True
    assert mission.success_contract["approval_mode"] == "per_step"
    plan_preview = next(node for node in mission.graph.nodes if node.node_id == "plan_preview")
    assert plan_preview.kind == "probe"
    work_nodes = [node for node in mission.graph.nodes if node.node_id.startswith("step_")]
    assert work_nodes[0].depends_on == ["plan_preview"]
    assert work_nodes[0].metadata["approval_required"] is True


@pytest.mark.asyncio
async def test_per_step_approval_blocks_then_resumes_direct_execution(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DirectIntentAgent()

    mission = await runtime.create_mission(
        "Masaüstüne note.txt dosyasına 'Merhaba Elyan' yaz ama sorarak ilerle",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "waiting_approval"
    assert not any("direct_intent" in call for call in agent.calls)

    pending = runtime.pending_approvals(owner="local")
    while pending:
        await runtime.resolve_approval(pending[0]["approval_id"], True, agent=agent)
        mission = await runtime.run_mission(mission.mission_id, agent=agent)
        pending = runtime.pending_approvals(owner="local")

    assert mission is not None
    assert mission.status == "completed"
    assert any("direct_intent" in call for call in agent.calls)


@pytest.mark.asyncio
async def test_file_node_accepts_direct_payload_file_path_as_artifact(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _FilePathDirectIntentAgent()

    mission = await runtime.create_mission(
        "Masaüstüne direct_note.txt dosyasına 'Merhaba' yaz",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "completed"
    assert any(str(record.path or "").endswith("direct-file-note.txt") for record in mission.evidence)


@pytest.mark.asyncio
async def test_run_mission_times_out_hanging_browser_node(tmp_path: Path, monkeypatch):
    runtime = MissionRuntime(storage_dir=tmp_path)

    class _HangingAgent:
        async def process_envelope(self, text, channel="dashboard", metadata=None, attachments=None):
            _ = (text, channel, metadata, attachments)
            await asyncio.sleep(3600)

    mission = await runtime.create_mission(
        "Safari'de openai.com aç",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )

    original_wait_for = asyncio.wait_for

    async def _fast_wait_for(awaitable, timeout):
        _ = timeout
        return await original_wait_for(awaitable, 0.01)

    monkeypatch.setattr("core.mission_control.asyncio.wait_for", _fast_wait_for)

    mission = await runtime.run_mission(mission.mission_id, agent=_HangingAgent())

    assert mission is not None
    assert mission.status == "failed"
    browser_node = next(node for node in mission.graph.nodes if node.node_id == "browser_action")
    assert browser_node.status == "failed"
    assert "zaman aşımına" in (browser_node.summary or "")


@pytest.mark.asyncio
async def test_browser_direct_intent_adds_proof_and_passes_verifier(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _BrowserDirectIntentAgent()

    mission = await runtime.create_mission(
        "Safari'de https://openai.com aç",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "completed"
    assert agent.shot_calls == 1
    assert any(str(record.path or "").endswith("browser-proof.png") for record in mission.evidence)


@pytest.mark.asyncio
async def test_browser_search_goal_prefers_direct_search_url(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _BrowserSearchDirectIntentAgent()

    mission = await runtime.create_mission(
        "Safari'de python docs ara",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "completed"
    assert agent.direct_intents
    direct_intent = agent.direct_intents[0]
    assert direct_intent["action"] == "open_url"
    assert "google.com/search" in direct_intent["params"]["url"]
    assert "python+docs" in direct_intent["params"]["url"]


@pytest.mark.asyncio
async def test_mission_to_dict_exposes_timeline_and_final_deliverable(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()

    mission = await runtime.create_mission(
        "Kısa rapor hazırla",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    payload = mission.to_dict()
    assert payload["final_deliverable"] == payload["deliverable"]
    assert payload["timeline"] == payload["events"]


@pytest.mark.asyncio
async def test_run_mission_persists_research_quality_metadata(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent(
        response_metadata={
            "claim_coverage": 0.92,
            "critical_claim_coverage": 1.0,
            "uncertainty_count": 1,
            "conflict_count": 0,
            "manual_review_claim_count": 0,
            "quality_status": "pass",
            "source_count": 5,
            "avg_reliability": 0.81,
            "claim_map_path": "/tmp/claim_map.json",
            "revision_summary_path": "/tmp/revision_summary.txt",
        }
    )

    mission = await runtime.create_mission(
        "Detaylı araştırma yap ve rapor hazırla",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    quality = mission.metadata.get("quality_summary", {})
    assert quality.get("claim_coverage") == 0.92
    assert quality.get("critical_claim_coverage") == 1.0
    assert quality.get("status") == "pass"
    snapshot = mission.snapshot()
    assert snapshot["quality_status"] == "pass"
    assert snapshot["claim_coverage"] == 0.92
    assert snapshot["claim_map_path"] == "/tmp/claim_map.json"
    assert mission.to_dict()["quality_summary"]["avg_reliability"] == 0.81

    restarted = MissionRuntime(storage_dir=tmp_path)
    reloaded = restarted.get_mission(mission.mission_id)
    assert reloaded is not None
    assert reloaded.quality_summary().get("claim_coverage") == 0.92
    assert reloaded.snapshot()["quality_status"] == "pass"


@pytest.mark.asyncio
async def test_high_risk_node_waits_for_approval_and_can_resume(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()

    mission = await runtime.create_mission(
        "Production deploy hazırla ve yayınla",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)

    assert mission is not None
    assert mission.status == "waiting_approval"
    pending = runtime.pending_approvals(owner="local")
    assert pending

    while pending:
        resumed = await runtime.resolve_approval(pending[0]["approval_id"], True, agent=agent)
        assert resumed is not None
        mission = await runtime.run_mission(mission.mission_id, agent=agent)
        pending = runtime.pending_approvals(owner="local")

    assert mission is not None
    assert mission.status == "completed"

@pytest.mark.asyncio
async def test_save_skill_and_memory_snapshot_async(tmp_path: Path):
    runtime = MissionRuntime(storage_dir=tmp_path)
    agent = _DummyAgent()
    mission = await runtime.create_mission(
        "Landing page üret ve teslim et",
        user_id="local",
        channel="dashboard",
        mode="Balanced",
        agent=agent,
        auto_start=False,
    )
    mission = await runtime.run_mission(mission.mission_id, agent=agent)
    recipe = runtime.save_skill(mission.mission_id)

    assert recipe is not None
    memory = runtime.memory_snapshot(user_id="local")
    assert memory["ok"] is True
    assert memory["profile"]
    assert memory["workflow"]
    assert memory["task"]
    assert memory["evidence"]
