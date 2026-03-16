from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.agent import Agent
from core.away_mode import AwayTaskRegistry, away_completion_notifier
from core.task_brain import TaskBrain
import pytest

from core.sub_agent.manager import SubAgentManager
from core.sub_agent.session import SubAgentTask


def test_visual_actions_auto_share_attachments():
    agent = Agent.__new__(Agent)
    ctx = SimpleNamespace(
        action="take_screenshot",
        requires_evidence=False,
        runtime_policy={"response": {"share_attachments_default": True}},
    )
    ok = Agent._should_share_attachments(agent, "durum nedir", ctx, [{"path": "/tmp/shot.png"}])
    assert ok is True


def test_research_delivery_auto_shares_attachments():
    agent = Agent.__new__(Agent)
    ctx = SimpleNamespace(
        action="research_document_delivery",
        requires_evidence=False,
        runtime_policy={"response": {"share_attachments_default": True}},
    )
    ok = Agent._should_share_attachments(agent, "araştırma yap", ctx, [{"path": "/tmp/report.docx"}])
    assert ok is True


def test_advanced_research_auto_shares_attachments():
    agent = Agent.__new__(Agent)
    ctx = SimpleNamespace(
        action="advanced_research",
        requires_evidence=False,
        runtime_policy={"response": {"share_attachments_default": True}},
    )
    ok = Agent._should_share_attachments(agent, "araştırma yap", ctx, [{"path": "/tmp/report.md"}])
    assert ok is True


def test_screen_workflow_auto_shares_attachments():
    agent = Agent.__new__(Agent)
    ctx = SimpleNamespace(
        action="screen_workflow",
        requires_evidence=False,
        runtime_policy={"response": {"share_attachments_default": True}},
    )
    ok = Agent._should_share_attachments(agent, "durum nedir", ctx, [{"path": "/tmp/shot.png"}])
    assert ok is True


def test_format_result_text_prefers_screen_summary():
    agent = Agent.__new__(Agent)
    text = Agent._format_result_text(
        agent,
        {
            "success": True,
            "summary": "IDE acik ve terminalde hata gorunuyor.",
            "provider": "ollama/llava",
            "observations": [
                {
                    "stage": "before",
                    "summary": "IDE acik ve terminalde hata gorunuyor.",
                    "provider": "ollama/llava",
                }
            ],
        },
    )
    assert "IDE acik ve terminalde hata gorunuyor." in text
    assert "ollama/llava" in text


def test_format_result_text_reads_nested_raw_screen_summary():
    agent = Agent.__new__(Agent)
    text = Agent._format_result_text(
        agent,
        {
            "status": "success",
            "message": "İşlem tamamlandı.",
            "raw": {
                "success": True,
                "observations": [
                    {
                        "stage": "before",
                        "summary": "On planda Cursor acik, terminal gorunuyor.",
                        "provider": "fallback/operator_state",
                    }
                ],
            },
        },
    )
    assert "On planda Cursor acik, terminal gorunuyor." in text
    assert "fallback/operator_state" in text


def test_render_research_result_prefers_report_paths():
    text = Agent._render_research_result(
        {
            "success": True,
            "report_paths": ["/tmp/report.md"],
            "source_count": 6,
            "finding_count": 4,
            "quality_summary": {"critical_claim_coverage": 1.0, "uncertainty_count": 1},
            "summary": "Uzun özet burada olmalı ama gösterilmemeli.",
        }
    )
    assert text is not None
    assert text.startswith("Araştırma notu hazır: /tmp/report.md")
    assert "Kaynak: 6" in text
    assert "Uzun özet burada" not in text


def test_agent_detects_background_request_markers():
    assert Agent._should_schedule_away_task("bunu arka planda yap") is True
    assert Agent._should_schedule_away_task("hazır olunca gönder") is True
    assert Agent._should_schedule_away_task("normal cevap ver") is False


@pytest.mark.asyncio
async def test_process_envelope_queues_background_task(monkeypatch):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u1"
    agent.capability_router = SimpleNamespace(route=lambda text: SimpleNamespace(domain="research", workflow_id="research_workflow"))

    queued = SimpleNamespace(task_id="away_123")
    captured = {}

    async def _fake_submit(**kwargs):
        captured.update(kwargs)
        return queued

    monkeypatch.setattr("core.agent.background_task_runner.submit", _fake_submit)

    response = await Agent.process_envelope(
        agent,
        "bunu arka planda yap",
        channel="telegram",
        metadata={"autonomy_mode": "background"},
    )
    assert response.metadata["away_task_id"] == "away_123"
    assert response.metadata["workflow_id"] == "research_workflow"
    assert "siraya alindi" in response.text
    assert captured["metadata"]["auto_retry"] is True
    assert captured["metadata"]["max_retries"] == 2


def test_away_retry_policy_is_capability_aware():
    research = Agent._away_retry_policy("research", "research_workflow", {"autonomy_mode": "background"})
    screen = Agent._away_retry_policy("screen_operator", "screen_operator_workflow", {"autonomy_mode": "background"})
    general = Agent._away_retry_policy("general", "", {"autonomy_mode": "background"})

    assert research["max_retries"] == 2
    assert research["retry_on_partial"] is True
    assert screen["max_retries"] == 1
    assert screen["retry_on_partial"] is False
    assert general["retry_on_failure"] is True


@pytest.mark.asyncio
async def test_away_completion_notifier_sends_channel_delivery(monkeypatch):
    agent = Agent.__new__(Agent)
    agent._away_notifier_registered = False
    away_completion_notifier._callbacks = []

    delivered = []

    async def _fake_deliver(channel_type, channel_id, response):
        delivered.append((channel_type, channel_id, response.text, list(response.attachments or [])))
        return True

    class _FakeNotifications:
        async def send_notification(self, **kwargs):
            return "n1"

    monkeypatch.setattr("core.agent.channel_delivery_bridge.deliver", _fake_deliver)
    monkeypatch.setattr("core.agent.get_smart_notifications", lambda: _FakeNotifications())

    Agent._register_away_notifier(agent)

    record = SimpleNamespace(
        task_id="away_1",
        user_input="bitcoin araştır",
        state="completed",
        run_id="run1",
        result_summary="Rapor hazır",
        attachments=[{"path": "/tmp/report.docx", "type": "file"}],
        metadata={"channel_type": "telegram", "channel_id": "123"},
    )
    await away_completion_notifier.notify(record)

    assert delivered
    assert delivered[0][0] == "telegram"
    assert delivered[0][1] == "123"
    assert delivered[0][2] == "Rapor hazır"


@pytest.mark.asyncio
async def test_agent_initialize_starts_away_resume_loop(monkeypatch):
    agent = Agent.__new__(Agent)
    agent.kernel = SimpleNamespace(initialize=AsyncMock(), llm="llm")
    agent.llm = None

    started = {}

    monkeypatch.setattr(agent, "_build_away_task_handler", lambda: "handler")

    def _fake_set_resume_handler(handler):
        started["handler"] = handler

    async def _fake_start_resume_loop(handler=None, interval_s=30.0):
        started["loop"] = (handler, interval_s)

    monkeypatch.setattr("core.agent.background_task_runner.set_resume_handler", _fake_set_resume_handler)
    monkeypatch.setattr("core.agent.background_task_runner.start_resume_loop", _fake_start_resume_loop)

    ok = await Agent.initialize(agent)
    assert ok is True
    assert started["handler"] == "handler"
    assert started["loop"] == ("handler", 15.0)


@pytest.mark.asyncio
async def test_process_envelope_lists_active_away_tasks(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-list"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    registry.create(
        user_input="bitcoin araştır",
        user_id="u-list",
        channel="telegram",
        workflow_id="research_workflow",
    )
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    response = await Agent.process_envelope(agent, "aktif görevler", channel="telegram")
    assert response.status == "success"
    assert "Arka plan gorevleri:" in response.text
    assert "away_" in response.text


@pytest.mark.asyncio
async def test_process_envelope_returns_away_task_status(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-status"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="rapor hazırla",
        user_id="u-status",
        channel="telegram",
        workflow_id="research_workflow",
    )
    registry.update(record.task_id, state="running", result_summary="hazirlaniyor")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    response = await Agent.process_envelope(agent, f"görev durumu {record.task_id}", channel="telegram")
    assert response.status == "success"
    assert record.task_id in response.text
    assert "Durum: running" in response.text
    assert response.metadata["task"]["task_id"] == record.task_id


@pytest.mark.asyncio
async def test_process_envelope_retries_away_task(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-retry"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="kod yaz",
        user_id="u-retry",
        channel="telegram",
    )
    registry.update(record.task_id, state="failed", error="boom")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    async def _fake_retry(task_id):
        return registry.requeue(task_id)

    monkeypatch.setattr("core.agent.background_task_runner.retry", _fake_retry)

    response = await Agent.process_envelope(agent, f"{record.task_id} yeniden başlat", channel="telegram")
    assert response.status == "success"
    assert "yeniden siraya alindi" in response.text


@pytest.mark.asyncio
async def test_process_envelope_cancels_latest_active_away_task_without_id(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-cancel"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="uzun arastirma yap",
        user_id="u-cancel",
        channel="telegram",
    )
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    async def _fake_cancel(task_id):
        return registry.cancel(task_id)

    monkeypatch.setattr("core.agent.background_task_runner.cancel", _fake_cancel)

    response = await Agent.process_envelope(agent, "son görevi iptal et", channel="telegram")
    assert response.status == "success"
    assert record.task_id in response.text
    assert response.metadata["task"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_process_envelope_uses_latest_task_for_status_without_id(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-last-status"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="raporu bitir",
        user_id="u-last-status",
        channel="telegram",
        workflow_id="research_workflow",
    )
    registry.update(record.task_id, state="completed", result_summary="hazir")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    response = await Agent.process_envelope(agent, "arka plan görev durumu", channel="telegram")
    assert response.status == "success"
    assert record.task_id in response.text
    assert response.metadata["task"]["summary"] == "hazir"


@pytest.mark.asyncio
async def test_process_envelope_falls_back_to_latest_foreground_task_status(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent.current_user_id = "u-fg"
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    brain = TaskBrain(storage_path=tmp_path / "task_brain.json")
    task = brain.create_task(
        objective="react projesi üret",
        user_input="react projesi üret",
        channel="telegram",
        user_id="u-fg",
    )
    task.transition("completed", note="response_ready")
    brain.save_task(task)
    monkeypatch.setattr("core.agent.task_brain", brain)

    response = await Agent.process_envelope(agent, "görev durumu", channel="telegram")
    assert response.status == "success"
    assert task.task_id in response.text
    assert response.metadata["task"]["type"] == "foreground"


def test_build_resume_task_suggestion_prefers_resumable_away_task(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent._task_suggestion_cache = {}
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="bitcoin raporu hazırla",
        user_id="u-suggest",
        channel="telegram",
    )
    registry.update(record.task_id, state="failed")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    suggestion = Agent._build_resume_task_suggestion(agent, "u-suggest", "merhaba")
    assert suggestion is not None
    assert suggestion["task_id"] == record.task_id
    assert suggestion["suggested_action"] == "retry"


def test_build_resume_task_suggestion_suppresses_task_control_messages(monkeypatch, tmp_path):
    agent = Agent.__new__(Agent)
    agent._task_suggestion_cache = {}
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="ekrana bak",
        user_id="u-suggest-2",
        channel="telegram",
    )
    registry.update(record.task_id, state="partial")
    monkeypatch.setattr("core.agent.away_task_registry", registry)

    suggestion = Agent._build_resume_task_suggestion(agent, "u-suggest-2", "görev durumu")
    assert suggestion is None


@pytest.mark.asyncio
async def test_subagent_manager_injects_default_objective_and_success_criteria(monkeypatch):
    manager = SubAgentManager(agent=SimpleNamespace(), parent_session_id="root")
    task = SubAgentTask(name="Research", description="Kaynaklari topla")

    monkeypatch.setattr(manager, "_build_workspace", lambda *args, **kwargs: ("/tmp/subagent", "/tmp/subagent/MEMORY.txt"))

    def _fake_create_task(coro, name=None):
        coro.close()
        return SimpleNamespace(name=name)

    monkeypatch.setattr("asyncio.create_task", _fake_create_task)
    await manager.spawn("research", task, tools=["web_search"])

    assert task.objective == "Kaynaklari topla"
    assert len(task.success_criteria) == 3
