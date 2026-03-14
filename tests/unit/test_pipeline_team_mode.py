from types import SimpleNamespace

import pytest

from core.pipeline import (
    PipelineContext,
    StageExecute,
    StageRoute,
    StageVerify,
    _extract_research_payload,
    _build_assist_mode_preview,
    _build_low_confidence_actionable_clarification,
    _job_type_from_action,
    _looks_simple_app_control_command,
    _looks_actionable_input,
    _resolve_execution_mode,
    _resolve_model_a_policy,
    _should_realign_to_capability,
    _try_model_a_intent_rescue,
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
async def test_stage_route_populates_world_snapshot(monkeypatch):
    class _World:
        def build_snapshot(self, **kwargs):
            _ = kwargs
            return {
                "domains": ["system"],
                "strategy_hints": ["Verify frontmost app and state before UI or terminal actions."],
                "similar_experiences": [{"id": 1, "goal": "safari ac"}],
                "summary": "domains=system; strategy=Verify frontmost app and state before UI or terminal actions.",
            }

    async def _fake_recall(*_args, **_kwargs):
        return {"conversation": [], "episodic": [], "semantic": []}

    monkeypatch.setattr("core.memory.unified.memory.recall", _fake_recall)
    monkeypatch.setattr("core.world_model.get_world_model", lambda: _World())

    agent = _DummyAgent()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "open_app", "params": {"app_name": "Safari"}})
    agent.capability_router = None

    ctx = PipelineContext(user_input="safari ac", user_id="u1", channel="cli")
    out = await StageRoute().run(ctx, agent)

    assert out.world_snapshot.get("domains") == ["system"]
    assert out.telemetry.get("world_model", {}).get("experience_hits") == 1


def test_pipeline_resolve_execution_mode_prefers_metadata_override():
    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    ctx.runtime_policy = {
        "execution": {"mode": "operator"},
        "metadata": {"execution_mode": "assist"},
    }
    assert _resolve_execution_mode(ctx) == "assist"


def test_pipeline_build_assist_mode_preview_includes_plan():
    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    ctx.action = "open_app"
    ctx.intent = {"action": "open_app", "params": {"app_name": "Safari"}}
    ctx.plan = [{"id": "step_1", "action": "open_app", "description": "Safari aç"}]
    text = _build_assist_mode_preview(ctx)
    assert "Assist Mode" in text
    assert "Intent: open_app" in text
    assert "Plan:" in text


@pytest.mark.asyncio
async def test_stage_execute_assist_mode_returns_preview_without_execution():
    class _CountAgent(_DummyAgent):
        def __init__(self):
            super().__init__()
            self.direct_calls = 0
            self.tool_calls = 0

        def _should_run_direct_intent(self, intent, user_input):
            _ = (intent, user_input)
            return True

        async def _run_direct_intent(self, *args, **kwargs):
            self.direct_calls += 1
            _ = (args, kwargs)
            return "should_not_run"

        async def _execute_tool(self, tool_name, params, **kwargs):
            self.tool_calls += 1
            _ = (tool_name, params, kwargs)
            return {"success": True}

    agent = _CountAgent()
    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    ctx.action = "open_app"
    ctx.intent = {"action": "open_app", "params": {"app_name": "Safari"}}
    ctx.job_type = "system_automation"
    ctx.runtime_policy = {"execution": {"mode": "assist"}, "metadata": {}}

    out = await StageExecute().run(ctx, agent)
    assert "Assist Mode" in out.final_response
    assert out.action == "chat"
    assert agent.direct_calls == 0
    assert agent.tool_calls == 0


@pytest.mark.asyncio
async def test_stage_execute_chat_mode_blocks_actionable_execution():
    class _CountAgent(_DummyAgent):
        def __init__(self):
            super().__init__()
            self.direct_calls = 0

        def _should_run_direct_intent(self, intent, user_input):
            _ = (intent, user_input)
            return True

        async def _run_direct_intent(self, *args, **kwargs):
            self.direct_calls += 1
            _ = (args, kwargs)
            return "should_not_run"

    agent = _CountAgent()
    ctx = PipelineContext(user_input="masaüstündeki dosyaları sil", user_id="u1", channel="cli")
    ctx.action = "delete_file"
    ctx.intent = {"action": "delete_file", "params": {"path": "~/Desktop/not.txt"}}
    ctx.job_type = "file_operations"
    ctx.runtime_policy = {"execution": {"mode": "chat"}, "metadata": {}}

    out = await StageExecute().run(ctx, agent)
    assert "Chat Mode aktif" in out.final_response
    assert out.action == "chat"
    assert agent.direct_calls == 0


@pytest.mark.asyncio
async def test_stage_execute_direct_policy_block_skips_fallback_paths():
    class _PolicyBlockAgent(_DummyAgent):
        def __init__(self):
            super().__init__()
            self._last_direct_intent_payload = {
                "action": "multi_task",
                "success": False,
                "failure_class": "policy_block",
                "failed_step": {"failure_class": "policy_block"},
            }

        def _should_run_direct_intent(self, intent, user_input):
            _ = (intent, user_input)
            return True

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            return "Hata: Security policy blocked this action."

    agent = _PolicyBlockAgent()
    ctx = PipelineContext(user_input="terminalde rm -rf / komutunu çalıştır", user_id="u1", channel="cli")
    ctx.action = "run_safe_command"
    ctx.intent = {"action": "run_safe_command", "params": {"command": "rm -rf /"}}
    ctx.job_type = "system_automation"
    ctx.runtime_policy = {"execution": {"mode": "operator"}, "metadata": {}}

    out = await StageExecute().run(ctx, agent)
    assert "Security policy blocked" in out.final_response
    assert any(str(err).startswith("direct_intent_blocked:policy_block") for err in out.errors)


@pytest.mark.asyncio
async def test_stage_execute_team_mode_partial_falls_back_to_orchestrator(monkeypatch):
    decisions = []

    def _record(**kwargs):
        decisions.append(kwargs)

    monkeypatch.setattr("core.pipeline.record_orchestration_decision", _record)

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
    assert any(d.get("mode") == "team_mode" and d.get("selected") is True for d in decisions)
    assert any(d.get("mode") == "team_mode" and d.get("selected") is False for d in decisions)


@pytest.mark.asyncio
async def test_stage_execute_team_mode_attaches_team_telemetry(monkeypatch):
    class _FakeTeam:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def execute_project(self, brief):
            _ = brief
            return SimpleNamespace(
                status="success",
                summary="Team mode tamamlandı",
                outputs=[],
                telemetry={
                    "research_tasks": 1,
                    "avg_claim_coverage": 1.0,
                    "avg_critical_claim_coverage": 1.0,
                    "max_uncertainty_count": 0,
                },
            )

    monkeypatch.setattr("core.sub_agent.team.AgentTeam", _FakeTeam)

    ctx = PipelineContext(user_input="araştırma görevi", user_id="u1", channel="cli")
    ctx.job_type = "research"
    ctx.intent = {"action": "research_document_delivery", "params": {"topic": "Fourier"}}
    ctx.action = "research_document_delivery"
    ctx.complexity = 0.97
    ctx.team_mode_forced = True
    ctx.multi_agent_recommended = True
    ctx.capability_confidence = 0.95
    ctx.capability_plan = {"orchestration_mode": "multi_agent"}
    ctx.plan = [{"id": "subtask_1", "action": "research_document_delivery"}]

    stage = StageExecute()
    out = await stage.run(ctx, _DummyAgent())

    assert out.telemetry.get("team_mode", {}).get("avg_claim_coverage") == 1.0
    assert out.capability_plan.get("team_mode_telemetry", {}).get("research_tasks") == 1


@pytest.mark.asyncio
async def test_stage_execute_superpowers_brainstorms_before_code_changes(tmp_path):
    ctx = PipelineContext(user_input="login bug fix", user_id="u1", channel="cli")
    ctx.action = "write_file"
    ctx.job_type = "code_project"
    ctx.capability_domain = "code"
    ctx.workflow_id = "coding_workflow"
    ctx.workflow_profile = "superpowers_lite"
    ctx.requires_design_phase = True
    ctx.approval_status = "pending"
    ctx.runtime_policy = {
        "workflow": {
            "profile": "superpowers_lite",
            "allowed_domains": ["code", "debug", "api_integration", "full_stack_delivery"],
            "require_explicit_approval": True,
            "workspace_policy": "auto",
        },
        "metadata": {"run_dir": str(tmp_path / "run")},
    }

    out = await StageExecute().run(ctx, _DummyAgent())

    assert "Superpowers workflow aktif" in out.final_response
    assert out.action == "chat"
    assert (tmp_path / "run" / "artifacts" / "design.md").exists()


@pytest.mark.asyncio
async def test_stage_execute_superpowers_strict_blocks_without_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "core.pipeline.inspect_workspace",
        lambda **kwargs: {
            "workspace_mode": "strict_worktree_required",
            "isolated_workspace": str(tmp_path / "workspace"),
            "workspace_report_path": str(tmp_path / "run" / "artifacts" / "workspace_report.json"),
            "baseline_check_path": str(tmp_path / "run" / "artifacts" / "baseline_check.md"),
        },
    )

    ctx = PipelineContext(user_input="api refactor", user_id="u1", channel="cli")
    ctx.action = "write_file"
    ctx.job_type = "code_project"
    ctx.capability_domain = "full_stack_delivery"
    ctx.workflow_id = "coding_workflow"
    ctx.workflow_profile = "superpowers_strict"
    ctx.requires_design_phase = True
    ctx.approval_status = "approved"
    ctx.plan = [{"id": "task_1", "title": "Refactor API", "action": "write_file", "params": {"path": "app/api.py"}}]
    ctx.runtime_policy = {
        "workflow": {
            "profile": "superpowers_strict",
            "allowed_domains": ["code", "debug", "api_integration", "full_stack_delivery"],
            "require_explicit_approval": True,
            "workspace_policy": "require_worktree",
        },
        "metadata": {"run_dir": str(tmp_path / "run")},
    }

    out = await StageExecute().run(ctx, _DummyAgent())

    assert "worktree zorunlu" in out.final_response.lower()
    assert "workflow:worktree_required" in out.errors


@pytest.mark.asyncio
async def test_stage_execute_team_mode_respects_runtime_policy_parallel_override(monkeypatch):
    captured = {}
    decisions = []

    def _record(**kwargs):
        decisions.append(kwargs)

    monkeypatch.setattr("core.pipeline.record_orchestration_decision", _record)

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
    assert any(d.get("mode") == "team_mode" and d.get("selected") is True for d in decisions)


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


def test_pipeline_job_type_from_action_overrides_browser_task_for_screen_actions():
    assert _job_type_from_action("screen_workflow", "browser_task") == "system_automation"
    assert _job_type_from_action("analyze_screen", "browser_task") == "system_automation"


def test_pipeline_capability_realign_for_screen_status_phrase():
    assert _should_realign_to_capability(
        user_input="durum nedir",
        action="open_app",
        capability_domain="screen_operator",
        capability_confidence=0.91,
        capability_primary_action="screen_workflow",
        intent_confidence=0.42,
        override_threshold=0.5,
    ) is True


def test_pipeline_capability_realign_skips_simple_open_app():
    assert _should_realign_to_capability(
        user_input="safari aç",
        action="open_app",
        capability_domain="screen_operator",
        capability_confidence=0.91,
        capability_primary_action="screen_workflow",
        intent_confidence=0.85,
        override_threshold=0.5,
    ) is False


def test_pipeline_capability_realign_keeps_ui_control_phrase_for_screen_operator():
    assert _should_realign_to_capability(
        user_input="safariyi aç ve continue butonuna tıkla",
        action="open_app",
        capability_domain="screen_operator",
        capability_confidence=0.91,
        capability_primary_action="screen_workflow",
        intent_confidence=0.85,
        override_threshold=0.5,
    ) is True


def test_pipeline_capability_realign_skips_simple_multi_task_app_flow():
    assert _should_realign_to_capability(
        user_input="safari aç sonra chrome'a geç",
        action="multi_task",
        capability_domain="screen_operator",
        capability_confidence=0.91,
        capability_primary_action="screen_workflow",
        intent_confidence=0.3,
        override_threshold=0.5,
    ) is False


def test_low_confidence_actionable_input_returns_clarification_prompt():
    ctx = PipelineContext(user_input="safari ac", user_id="u1", channel="cli")
    ctx.action = "unknown"
    ctx.intent = {"action": "unknown", "confidence": 0.12}
    ctx.intent_score = 0.1
    ctx.capability_confidence = 0.2
    prompt = _build_low_confidence_actionable_clarification(ctx)
    assert isinstance(prompt, str)
    assert "netlestirmem gerekiyor" in prompt.lower()


def test_simple_app_control_command_guard():
    assert _looks_simple_app_control_command("safari aç") is True
    assert _looks_simple_app_control_command("chrome'a geç") is True
    assert _looks_simple_app_control_command("safariyi aç ve devam butonuna tıkla") is False


def test_model_a_policy_defaults_without_runtime_overrides():
    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    enabled, model_path, min_conf, allowed = _resolve_model_a_policy(ctx)
    assert isinstance(enabled, bool)
    assert isinstance(model_path, str) and model_path
    assert 0.0 <= min_conf <= 1.0
    assert isinstance(allowed, list) and "open_app" in allowed


def test_model_a_intent_rescue_promotes_non_actionable_route():
    class _Agent:
        @staticmethod
        def _infer_model_a_intent(user_input, **kwargs):
            _ = (user_input, kwargs)
            return {"action": "open_app", "params": {"app_name": "Safari"}, "confidence": 0.91}

    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    ctx.action = "chat"
    ctx.job_type = "communication"
    ok = _try_model_a_intent_rescue(
        ctx,
        _Agent(),
        enabled=True,
        model_path="/tmp/model.json",
        min_confidence=0.7,
        allowed_actions=["open_app"],
    )
    assert ok is True
    assert ctx.action == "open_app"
    assert ctx.job_type == "system_automation"


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
async def test_stage_execute_preserves_screen_workflow_boundary_on_direct_failure():
    class _ScreenFailAgent(_DummyAgent):
        def _should_run_direct_intent(self, intent, user_input):
            _ = user_input
            return isinstance(intent, dict) and str(intent.get("action") or "") == "screen_workflow"

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            self._last_direct_intent_payload = {
                "success": False,
                "error": "vision_timeout:9.0s",
                "artifacts": [{"path": "/tmp/screen.png", "type": "image"}],
                "ui_map": {"frontmost_app": "Cursor", "running_apps": ["Cursor"]},
            }
            return "Hata: vision_timeout:9.0s"

    ctx = PipelineContext(user_input="ekranda ne var", user_id="u1", channel="cli")
    ctx.job_type = "browser_task"
    ctx.intent = {"action": "screen_workflow", "params": {"instruction": "ekranda ne var", "mode": "inspect"}}
    ctx.action = "screen_workflow"

    out = await StageExecute().run(ctx, _ScreenFailAgent())

    assert "vision_timeout:9.0s" in (out.final_response or "")
    assert len(out.tool_results) == 1
    assert out.tool_results[0]["source"] == "direct_intent"
    assert isinstance(out.tool_results[0].get("raw"), dict)


@pytest.mark.asyncio
async def test_stage_execute_marks_app_control_unverified_as_failure():
    class _AppVerifyFailAgent(_DummyAgent):
        def _should_run_direct_intent(self, intent, user_input):
            _ = user_input
            return isinstance(intent, dict) and str(intent.get("action") or "") == "open_app"

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            self._last_direct_intent_payload = {
                "success": True,
                "verified": False,
                "verification_warning": "frontmost_app uyumsuz: beklenen=Safari, görünen=Finder",
                "frontmost_app": "Finder",
            }
            return "Safari opened."

    ctx = PipelineContext(user_input="safari aç", user_id="u1", channel="cli")
    ctx.job_type = "system_automation"
    ctx.intent = {"action": "open_app", "params": {"app_name": "Safari"}}
    ctx.action = "open_app"

    out = await StageExecute().run(ctx, _AppVerifyFailAgent())
    assert "Safari opened." in (out.final_response or "")
    assert "uyumsuz" in (out.final_response or "").lower()
    assert any(str(err).startswith("direct_intent_unverified:open_app") for err in out.errors)
    assert out.tool_results and out.tool_results[0].get("success") is False


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
    ctx.tool_results = [
        {
            "sources": [{"url": "https://example.com/report"}],
            "result": {
                "research_contract": {
                    "claim_list": [{"claim_id": "c1"}],
                    "citation_map": {"c1": [{"url": "https://example.com/report"}]},
                    "critical_claim_ids": ["c1"],
                    "uncertainty_log": [],
                    "conflicts": [],
                },
                "quality_summary": {
                    "claim_coverage": 1.0,
                    "critical_claim_coverage": 0.5,
                    "uncertainty_count": 2,
                },
            },
        }
    ]

    out = await StageVerify().run(ctx, _DummyAgent())

    contract = out.qa_results.get("output_contract", {})
    assert contract.get("kind") == "research"
    assert contract.get("sources_found") >= 1
    assert "Araştırma kalite özeti" in out.final_response
    assert "https://example.com/report" in out.final_response
    assert "Güven skoru" in out.final_response
    assert "Kritik claim coverage" in out.final_response


def test_extract_research_payload_keeps_quality_summary_from_nested_result():
    payload = _extract_research_payload(
        [
            {
                "task": "research",
                "result": {
                    "research_contract": {
                        "claim_list": [{"claim_id": "c1"}],
                        "citation_map": {"c1": [{"url": "https://example.com"}]},
                        "critical_claim_ids": ["c1"],
                        "uncertainty_log": [],
                        "conflicts": [],
                    },
                    "quality_summary": {
                        "claim_coverage": 1.0,
                        "critical_claim_coverage": 0.5,
                        "uncertainty_count": 2,
                    },
                    "claim_map_path": "/tmp/claim_map.json",
                },
            }
        ]
    )
    assert isinstance(payload, dict)
    assert payload.get("quality_summary", {}).get("critical_claim_coverage") == 0.5
    assert payload.get("claim_map_path") == "/tmp/claim_map.json"
