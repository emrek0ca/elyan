from __future__ import annotations

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
