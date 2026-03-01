from types import SimpleNamespace

import pytest

from core.pipeline import (
    PipelineContext,
    StageExecute,
    StageVerify,
    _job_type_from_action,
    _looks_actionable_input,
    _try_llm_intent_rescue,
)


class _DummyAgent:
    def __init__(self):
        self.llm = SimpleNamespace(generate=self._generate)

    async def _generate(self, prompt, **kwargs):
        _ = (prompt, kwargs)
        return "ok"

    def _should_run_direct_intent(self, intent, user_input):
        _ = (intent, user_input)
        return False

    async def _run_direct_intent(self, *args, **kwargs):
        _ = (args, kwargs)
        return None

    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        return {"success": True}

    @staticmethod
    def _format_result_text(result):
        return str(result)

    @staticmethod
    def _sanitize_research_topic(topic, **kwargs):
        _ = kwargs
        return topic

    @staticmethod
    def _extract_topic(text, *_args, **_kwargs):
        return text


@pytest.mark.asyncio
async def test_stage_execute_team_mode_partial_falls_back_to_orchestrator(monkeypatch):
    class _FakeTeam:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def execute_project(self, brief):
            _ = brief
            return SimpleNamespace(
                status="partial",
                summary="Team mode tamamlandı: completed=1 failed=2 stages=2",
                outputs=[{"task": "demo", "status": "failed"}],
            )

    class _FakeOrchestrator:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def manage_flow(self, plan, original_input):
            _ = (plan, original_input)
            return "ORCH_FALLBACK_OK"

    monkeypatch.setattr("core.sub_agent.team.AgentTeam", _FakeTeam)
    monkeypatch.setattr("core.multi_agent.orchestrator.AgentOrchestrator", _FakeOrchestrator)

    ctx = PipelineContext(
        user_input="karmaşık görev",
        user_id="u1",
        channel="cli",
    )
    ctx.job_type = "system_automation"
    ctx.intent = {"action": "run_safe_command", "params": {"command": "echo ok"}}
    ctx.action = "run_safe_command"
    ctx.complexity = 0.98
    ctx.team_mode_forced = True
    ctx.multi_agent_recommended = True
    ctx.capability_confidence = 0.95
    ctx.capability_plan = {"orchestration_mode": "multi_agent"}
    ctx.plan = [{"id": "subtask_1", "action": "run_safe_command"}]

    stage = StageExecute()
    out = await stage.run(ctx, _DummyAgent())

    assert "ORCH_FALLBACK_OK" in out.final_response
    assert any(str(e).startswith("team_mode_incomplete:") for e in out.errors)


@pytest.mark.asyncio
async def test_stage_execute_team_mode_respects_runtime_policy_parallel_override(monkeypatch):
    captured = {}

    class _FakeTeam:
        def __init__(self, _agent, config):
            captured["max_parallel"] = config.max_parallel
            captured["timeout_s"] = config.timeout_s
            captured["max_retries"] = config.max_retries_per_task
            captured["use_llm_planner"] = config.use_llm_planner

        async def execute_project(self, brief):
            _ = brief
            return SimpleNamespace(status="success", summary="TEAM_OK", outputs=[])

    monkeypatch.setattr("core.sub_agent.team.AgentTeam", _FakeTeam)

    ctx = PipelineContext(user_input="karmaşık görev", user_id="u1", channel="cli")
    ctx.job_type = "system_automation"
    ctx.intent = {"action": "run_safe_command", "params": {"command": "echo ok"}}
    ctx.action = "run_safe_command"
    ctx.complexity = 0.98
    ctx.team_mode_forced = True
    ctx.multi_agent_recommended = True
    ctx.capability_confidence = 0.95
    ctx.capability_plan = {"orchestration_mode": "multi_agent"}
    ctx.plan = [{"id": "subtask_1", "action": "run_safe_command"}]
    ctx.runtime_policy = {
        "planning": {"use_llm": False},
        "orchestration": {
            "team_max_parallel": 2,
            "team_timeout_s": 120,
            "team_max_retries_per_task": 3,
        },
    }

    stage = StageExecute()
    out = await stage.run(ctx, _DummyAgent())

    assert "TEAM_OK" in out.final_response
    assert captured.get("max_parallel") == 2
    assert captured.get("timeout_s") == 120
    assert captured.get("max_retries") == 3
    assert captured.get("use_llm_planner") is False


def test_pipeline_actionable_input_heuristic():
    assert _looks_actionable_input("masaüstündeki duvar kağıdını köpek resmi yap", [])
    assert _looks_actionable_input("1) klasör oluştur 2) dosya yaz", [])
    assert _looks_actionable_input("https://httpbin.org/get için health check yap", [])
    assert not _looks_actionable_input("fatih sultan mehmet kimdir?", [])
    assert not _looks_actionable_input("api nedir?", [])


def test_pipeline_job_type_from_action_for_communication_route():
    assert _job_type_from_action("set_wallpaper", "communication") == "system_automation"
    assert _job_type_from_action("http_request", "communication") == "api_integration"
    assert _job_type_from_action("write_file", "communication") == "file_operations"
    assert _job_type_from_action("edit_text_file", "communication") == "file_operations"


@pytest.mark.asyncio
async def test_stage_execute_rescues_actionable_chat_into_direct_intent():
    class _RescueAgent(_DummyAgent):
        def __init__(self):
            super().__init__()
            self.direct_calls = 0

        def _infer_general_tool_intent(self, user_input):
            _ = user_input
            return {"action": "set_wallpaper", "params": {"search_query": "dog wallpaper"}}

        def _should_run_direct_intent(self, intent, user_input):
            _ = user_input
            return isinstance(intent, dict) and str(intent.get("action") or "") == "set_wallpaper"

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            self.direct_calls += 1
            return "Duvar kağıdı güncellendi."

    agent = _RescueAgent()
    ctx = PipelineContext(user_input="masaüstündeki duvar kağıdını köpek resmi yap", user_id="u1", channel="cli")
    ctx.intent = {"action": "chat", "params": {"message": ctx.user_input}}
    ctx.action = "chat"
    ctx.job_type = "communication"

    stage = StageExecute()
    out = await stage.run(ctx, agent)

    assert "Duvar kağıdı güncellendi." in out.final_response
    assert out.action == "set_wallpaper"
    assert out.job_type == "system_automation"
    assert agent.direct_calls == 1


@pytest.mark.asyncio
async def test_try_llm_intent_rescue_accepts_high_confidence():
    class _Agent:
        async def _infer_llm_tool_intent(self, user_input, **kwargs):
            _ = (user_input, kwargs)
            return {"action": "http_request", "params": {"url": "https://httpbin.org/get"}, "confidence": 0.92}

    ctx = PipelineContext(user_input="httpbin için get at", user_id="u1", channel="cli")
    ctx.action = "chat"
    ctx.job_type = "communication"
    ok = await _try_llm_intent_rescue(ctx, _Agent(), min_confidence=0.62)
    assert ok is True
    assert ctx.action == "http_request"
    assert ctx.job_type == "api_integration"


@pytest.mark.asyncio
async def test_try_llm_intent_rescue_rejects_low_confidence():
    class _Agent:
        async def _infer_llm_tool_intent(self, user_input, **kwargs):
            _ = (user_input, kwargs)
            return {"action": "http_request", "params": {"url": "https://httpbin.org/get"}, "confidence": 0.30}

    ctx = PipelineContext(user_input="httpbin için get at", user_id="u1", channel="cli")
    ctx.action = "chat"
    ctx.job_type = "communication"
    ok = await _try_llm_intent_rescue(ctx, _Agent(), min_confidence=0.62)
    assert ok is False
    assert ctx.action == "chat"


@pytest.mark.asyncio
async def test_stage_verify_code_quality_contract_adds_missing_gate_note():
    ctx = PipelineContext(user_input="python kodu yaz", user_id="u1", channel="cli")
    ctx.is_code_job = True
    ctx.final_response = ""
    ctx.tool_results = [{"tool": "write_file", "result": {"path": "~/Desktop/app.py"}}]

    out = await StageVerify().run(ctx, _DummyAgent())

    contract = out.qa_results.get("output_contract", {})
    assert contract.get("kind") == "code"
    assert set(contract.get("signals", {}).get("missing", [])) == {"tests", "lint", "typecheck"}
    assert "Kalite kontrol özeti" in out.final_response


@pytest.mark.asyncio
async def test_stage_verify_code_quality_contract_passes_with_signals():
    ctx = PipelineContext(user_input="python kodu yaz", user_id="u1", channel="cli")
    ctx.is_code_job = True
    ctx.final_response = ""
    ctx.tool_results = [
        {"tool": "run_safe_command", "result": {"output": "pytest -q passed"}},
        {"tool": "run_safe_command", "result": {"output": "ruff check ."}},
        {"tool": "run_safe_command", "result": {"output": "mypy src"}},
    ]

    out = await StageVerify().run(ctx, _DummyAgent())

    contract = out.qa_results.get("output_contract", {})
    assert contract.get("kind") == "code"
    assert contract.get("status") == "pass"
    assert contract.get("signals", {}).get("missing", []) == []
    assert "Kalite kontrol özeti" not in str(out.final_response or "")


@pytest.mark.asyncio
async def test_stage_verify_research_contract_appends_summary_sections():
    ctx = PipelineContext(user_input="yapay zeka trendlerini araştır", user_id="u1", channel="cli")
    ctx.action = "advanced_research"
    ctx.final_response = "Araştırma tamamlandı."
    ctx.tool_results = [{"sources": [{"url": "https://example.com/report"}]}]

    out = await StageVerify().run(ctx, _DummyAgent())

    contract = out.qa_results.get("output_contract", {})
    assert contract.get("kind") == "research"
    assert contract.get("sources_found") >= 1
    assert "Araştırma kalite özeti" in out.final_response
    assert "https://example.com/report" in out.final_response
    assert "Güven skoru" in out.final_response
