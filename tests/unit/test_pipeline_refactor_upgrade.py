from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.pipeline import (
    PipelineContext,
    StageValidate,
    StageExecute,
    StageVerify,
    StageDeliver,
    _try_llm_intent_rescue,
    _evaluate_completion_gate,
    _repair_screen_completion,
    _should_realign_to_capability,
)
from core.pipeline_upgrade.executor import fallback_ladder, diff_only_failed_steps, collect_paths_from_tool_results
from core.pipeline_upgrade.contracts import (
    verify_taskspec_contract,
    build_reflexion_hint,
    build_critic_review_prompt,
)
from core.pipeline_upgrade.verifier import (
    enforce_output_contract,
    verify_code_gates,
    verify_asset_gates,
)


class _IntentAgent:
    def __init__(self, payload):
        self.payload = payload

    async def _infer_llm_tool_intent(self, user_input, **kwargs):
        _ = (user_input, kwargs)
        return self.payload


class _DummyAgent:
    pass


@pytest.mark.asyncio
async def test_validate_stage_initializes_runtime_trace():
    ctx = PipelineContext(user_input="selam", user_id="u1", channel="cli")
    ctx = await StageValidate().run(ctx, _DummyAgent())
    assert ctx.telemetry.get("request_id", "").startswith("req_")
    assert ctx.telemetry.get("delivery_mode") == "cli"


@pytest.mark.asyncio
async def test_intent_json_envelope_enforced_rejects_invalid_payload():
    ctx = PipelineContext(user_input="httpbin için get at", user_id="u1", channel="cli")
    ctx.action = "chat"
    ctx.runtime_policy = {"feature_flags": {"upgrade_intent_json_envelope": True}}

    ok = await _try_llm_intent_rescue(ctx, _IntentAgent({"action": "http_request", "confidence": 0.9}), min_confidence=0.6)
    assert ok is False
    assert ctx.action == "chat"


@pytest.mark.asyncio
async def test_intent_json_envelope_enforced_accepts_valid_payload():
    ctx = PipelineContext(user_input="httpbin için get at", user_id="u1", channel="cli")
    ctx.action = "chat"
    ctx.runtime_policy = {"feature_flags": {"upgrade_intent_json_envelope": True}}

    payload = {
        "intent": {"action": "http_request", "params": {"url": "https://httpbin.org/get"}},
        "confidence": 0.91,
        "required_artifacts": ["response.json"],
        "tools_needed": ["http_request"],
        "safety_flags": ["network_read_only"],
        "assumptions": ["public endpoint"],
    }
    ok = await _try_llm_intent_rescue(ctx, _IntentAgent(payload), min_confidence=0.6)

    assert ok is True
    assert ctx.action == "http_request"
    assert ctx.required_artifacts == ["response.json"]


def test_output_contract_enforcement_blocks_empty_files_and_missing_evidence(tmp_path):
    p = tmp_path / "report.md"
    p.write_text("", encoding="utf-8")

    out = enforce_output_contract(
        job_type="file_operations",
        expected_extensions=[".md"],
        produced_paths=[str(p)],
        evidence_checks=[],
    )

    assert out["ok"] is False
    assert "non_empty_files" in out["errors"]
    assert "evidence_required" in out["errors"]


def test_taskspec_contract_blocks_empty_document_artifact(tmp_path):
    target = tmp_path / "report.md"
    target.write_text("", encoding="utf-8")

    task_spec = {
        "intent": "filesystem_batch",
        "deliverables": [{"name": "report.md", "kind": "file", "required": True}],
        "artifacts_expected": [{"path": str(target), "type": "file", "must_exist": True}],
        "success_criteria": ["artifacts_expected_exist", "artifact_file_not_empty"],
    }

    out = verify_taskspec_contract(
        task_spec=task_spec,
        job_type="file_operations",
        final_response="tamam",
        tool_results=[{"success": True, "path": str(target)}],
        produced_paths=[str(target)],
    )

    assert out["ok"] is False
    assert "criteria:artifact_file_not_empty" in out["failed"]
    assert "document:empty_artifact" in out["failed"]


def test_build_reflexion_hint_uses_job_profile():
    hint = build_reflexion_hint(
        verification_payload={"failed": ["document:empty_artifact", "criteria:artifact_file_not_empty"]},
        job_type="file_operations",
    )
    assert "Reflexion next:" in hint
    assert "dosya artifact" in hint


def test_fallback_ladder_order_is_progressive():
    assert fallback_ladder() == [
        "same_plan_different_model",
        "reduced_minimal_plan",
        "deterministic_tool_macro",
        "ask_user",
    ]


def test_diff_based_repair_returns_only_failing_steps():
    plan = [
        {"id": "s1", "action": "read_file"},
        {"id": "s2", "action": "write_file"},
        {"id": "s3", "action": "run_safe_command"},
    ]
    out = diff_only_failed_steps(plan, ["s2"])
    assert [step["id"] for step in out] == ["s2"]


def test_verify_code_gates_can_use_tool_outputs_without_response_markers():
    out = verify_code_gates(
        final_response="completed",
        produced_paths=["/tmp/main.py"],
        tool_results=[
            {"result": {"output": "ruff check ."}},
            {"result": {"output": "pytest -q tests passed"}},
            {"result": {"output": "mypy src"}},
        ],
    )
    assert out["ok"] is True
    assert out["failed"] == []


def test_verify_asset_gates_enforces_dimensions_and_safe_area():
    out = verify_asset_gates(
        attachment_index=[
            {
                "path": "/tmp/banner.png",
                "type": "png",
                "size_bytes": 1024,
                "width": 1920,
                "height": 1080,
                "safe_area_ratio": 0.8,
            }
        ],
        safe_area_min=0.85,
    )
    assert out["ok"] is False
    assert "safe_area" in out["failed"]
    assert out["dimensions_checked"] == 1


def test_build_critic_review_prompt_for_research_contains_qa_payload():
    prompt = build_critic_review_prompt(
        job_type="research",
        final_response="Fourier araştırması hazır.",
        qa_results={"research_gate": {"ok": False, "failed": ["sources"]}},
        errors=["research:sources"],
    )
    assert "research_gate" in prompt
    assert "verdict" in prompt


@pytest.mark.asyncio
async def test_verify_stage_builds_research_recovery_plan():
    class _LLM:
        async def generate(self, prompt, role="inference", user_id="local", **kwargs):
            _ = (prompt, role, user_id, kwargs)
            return "verdict: fail\nrisk: kaynak ve claim map eksik\nnext: research revise"

    class _Agent:
        def __init__(self):
            self.llm = _LLM()

    ctx = PipelineContext(user_input="AI agents hakkında araştırma yap", user_id="u1", channel="cli")
    ctx.job_type = "research"
    ctx.action = "research_document_delivery"
    ctx.final_response = "Kısa rapor hazır."
    ctx.llm_response = "Kısa rapor hazır."
    ctx.tool_results = []
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _Agent())

    assert ctx.delivery_blocked is True
    assert ctx.qa_results.get("research_failure", {}).get("class") == "planning_failure"
    assert ctx.qa_results.get("research_recovery_strategy", {}).get("kind") == "research_revision_plan"
    repair_plan = ctx.qa_results.get("research_repair_plan", {})
    assert repair_plan.get("repairable") is True
    steps = list(repair_plan.get("steps") or [])
    assert "En az 3 güvenilir kaynak ekle" in steps
    assert any("payload" in step.lower() for step in steps)
    assert "Research next:" in (ctx.final_response or "")


@pytest.mark.asyncio
async def test_verify_stage_skips_communication_jobs_without_critic_call():
    critic = AsyncMock(side_effect=AssertionError("critic should not run for communication jobs"))

    class _Agent:
        def __init__(self):
            self.llm = SimpleNamespace(generate=critic)

    ctx = PipelineContext(user_input="merhaba", user_id="u1", channel="cli")
    ctx.job_type = "communication"
    ctx.final_response = "Merhaba"
    ctx.llm_response = "Merhaba"
    ctx.tool_results = []

    ctx = await StageVerify().run(ctx, _Agent())

    assert ctx.verified is True
    assert ctx.delivery_blocked is False
    assert ctx.qa_results.get("verify_skipped", {}).get("reason") == "communication"
    assert ctx.phase_records.get("verify", {}).get("skipped") is True
    critic.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_ladder_diff_repair_retries_only_failed_steps(monkeypatch):
    class _ExecAgent:
        def __init__(self):
            self.llm = SimpleNamespace(generate=self._generate)
            self.calls = []

        async def _generate(self, prompt, **kwargs):
            _ = (prompt, kwargs)
            return "fallback"

        def _should_run_direct_intent(self, intent, user_input):
            _ = (intent, user_input)
            return False

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            return None

        async def _execute_tool(self, tool_name, params, **kwargs):
            _ = kwargs
            self.calls.append((tool_name, dict(params or {})))
            return {"success": True, "result": {"path": "/tmp/main.py", "success": True}}

        @staticmethod
        def _format_result_text(result):
            return str(result)

    class _FakeCDG:
        async def create_plan(self, *args, **kwargs):
            _ = (args, kwargs)
            node = SimpleNamespace(
                id="n1",
                name="write",
                action="write_file",
                params={"path": "/tmp/main.py", "content": "print('x')"},
                state=SimpleNamespace(value="failed"),
                result={"success": False},
                error="write failed",
            )
            return SimpleNamespace(status="failed", nodes=[node])

        async def execute(self, plan, executor):
            _ = executor
            return plan

        def get_evidence_manifest(self, plan):
            _ = plan
            return {"artifacts": []}

    monkeypatch.setattr("core.cdg_engine.cdg_engine", _FakeCDG())

    ctx = PipelineContext(user_input="kod yaz", user_id="u1", channel="cli")
    ctx.job_type = "code_project"
    ctx.action = "write_file"
    ctx.intent = {"action": "write_file", "params": {"path": "/tmp/main.py", "content": "print('x')"}}
    ctx.runtime_policy = {"feature_flags": {"upgrade_fallback_ladder": True}}
    ctx.complexity = 0.4

    agent = _ExecAgent()
    out = await StageExecute().run(ctx, agent)

    assert out.telemetry.get("repair_loops") == 1
    assert out.telemetry.get("fallback_ladder")
    assert "diff-repair" in (out.final_response or "").lower()
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_verify_gate_blocks_completed_delivery_when_strict_flag_enabled(tmp_path):
    p = tmp_path / "artifact_main.py"
    p.write_text("print('hello')\n", encoding="utf-8")

    ctx = PipelineContext(user_input="kod yaz", user_id="u1", channel="cli")
    ctx.is_code_job = True
    ctx.job_type = "code_project"
    ctx.final_response = "completed"
    ctx.llm_response = "completed"
    # Use a neutral path token to avoid accidental marker matches from pytest temp dirs.
    ctx.tool_results = [{"result": {"path": "/tmp/elyan_gate_main.py", "success": True}}]
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _DummyAgent())
    assert ctx.verified is False
    assert ctx.delivery_blocked is True

    ctx = await StageDeliver().run(ctx, _DummyAgent())
    assert ctx.delivery_blocked is True
    assert "Verify gate failed" in ctx.final_response


@pytest.mark.asyncio
async def test_verify_gate_uses_taskspec_contract_and_appends_reflexion_hint(tmp_path):
    target = tmp_path / "empty.md"
    target.write_text("", encoding="utf-8")

    ctx = PipelineContext(user_input="masaustune belge olustur", user_id="u1", channel="cli")
    ctx.job_type = "file_operations"
    ctx.action = "write_file"
    ctx.final_response = "tamam"
    ctx.llm_response = "tamam"
    ctx.intent = {
        "action": "write_file",
        "task_spec": {
            "intent": "filesystem_batch",
            "deliverables": [{"name": "empty.md", "kind": "file", "required": True}],
            "artifacts_expected": [{"path": str(target), "type": "file", "must_exist": True}],
            "success_criteria": ["artifacts_expected_exist", "artifact_file_not_empty"],
        },
    }
    ctx.tool_results = [{"result": {"path": str(target), "success": True}}]
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _DummyAgent())
    assert ctx.verified is False
    assert ctx.delivery_blocked is True
    assert "taskspec_contract" in ctx.qa_results
    assert "Reflexion next:" in ctx.final_response


@pytest.mark.asyncio
async def test_verify_gate_repairs_missing_document_artifact_via_taskspec_replay(tmp_path):
    target = tmp_path / "repair.md"

    class _RepairAgent:
        async def _execute_tool(self, tool_name, params, **kwargs):
            _ = kwargs
            if tool_name == "write_file":
                p = Path(str(params.get("path") or ""))
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(str(params.get("content") or ""), encoding="utf-8")
                return {"success": True, "path": str(p)}
            if tool_name == "create_folder":
                p = Path(str(params.get("path") or ""))
                p.mkdir(parents=True, exist_ok=True)
                return {"success": True, "path": str(p)}
            return {"success": False, "error": f"unexpected_tool:{tool_name}"}

        llm = None

    ctx = PipelineContext(user_input="masaustune belge olustur", user_id="u1", channel="cli")
    ctx.job_type = "file_operations"
    ctx.action = "write_file"
    ctx.final_response = "tamam"
    ctx.llm_response = "tamam"
    ctx.intent = {
        "action": "write_file",
        "task_spec": {
            "intent": "filesystem_batch",
            "task_id": "task_repair",
            "goal": "masaustune belge olustur",
            "user_goal": "masaustune belge olustur",
            "entities": {"path": str(target)},
            "deliverables": [{"name": "repair.md", "kind": "file", "required": True}],
            "constraints": {},
            "context_assumptions": [],
            "artifacts_expected": [{"path": str(target), "type": "file", "must_exist": True}],
            "checks": [],
            "rollback": [],
            "required_tools": ["write_file"],
            "tool_candidates": ["write_file"],
            "priority": "normal",
            "risk_level": "low",
            "success_criteria": ["artifacts_expected_exist", "artifact_file_not_empty"],
            "timeouts": {"step_timeout_s": 10, "run_timeout_s": 60},
            "retries": {"max_attempts": 1},
            "steps": [
                {
                    "id": "step_1",
                    "action": "write_file",
                    "path": str(target),
                    "content": "icerik",
                    "params": {"path": str(target), "content": "icerik"},
                    "success_criteria": ["artifact_file_exists", "artifact_file_not_empty"],
                }
            ],
        },
    }
    ctx.tool_results = []
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _RepairAgent())
    assert ctx.delivery_blocked is False
    assert ctx.verified is True
    assert target.exists() is True
    assert target.read_text(encoding="utf-8") == "icerik"
    repair_payload = ctx.qa_results.get("taskspec_contract_repair", {})
    assert repair_payload.get("repaired") is True
    assert repair_payload.get("strategy") == "taskspec_artifact_replay"
    assert ctx.qa_results.get("taskspec_failure", {}).get("class") == "planning_failure"
    assert ctx.qa_results.get("taskspec_recovery_strategy", {}).get("kind") == "replay_taskspec_artifact"


@pytest.mark.asyncio
async def test_verify_stage_uses_critic_role_for_code_jobs():
    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt, role="inference", user_id="local", **kwargs):
            self.calls.append({"prompt": prompt, "role": role, "user_id": user_id, "kwargs": kwargs})
            return "verdict: fail\nrisk: kalite kapısı eksik\nnext: lint ve test çalıştır"

    class _Agent:
        def __init__(self):
            self.llm = _LLM()

    ctx = PipelineContext(user_input="kod yaz", user_id="u1", channel="cli")
    ctx.is_code_job = True
    ctx.job_type = "code_project"
    ctx.final_response = "completed"
    ctx.llm_response = "completed"
    ctx.tool_results = [{"result": {"path": "/tmp/elyan_gate_main.py", "success": True}}]
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}
    ctx.hybrid_model = {"critic_role": "critic"}

    agent = _Agent()
    ctx = await StageVerify().run(ctx, agent)
    assert agent.llm.calls
    assert agent.llm.calls[0]["role"] == "critic"
    assert "critic_review" in ctx.qa_results


@pytest.mark.asyncio
async def test_verify_stage_builds_code_quality_gate_recovery_plan():
    class _LLM:
        async def generate(self, prompt, role="inference", user_id="local", **kwargs):
            _ = (prompt, role, user_id, kwargs)
            return "verdict: fail\nrisk: kalite kapıları eksik\nnext: quality gates"

    class _Agent:
        def __init__(self):
            self.llm = _LLM()

    ctx = PipelineContext(user_input="kod yaz", user_id="u1", channel="cli")
    ctx.is_code_job = True
    ctx.job_type = "code_project"
    ctx.action = "write_file"
    ctx.final_response = "completed"
    ctx.llm_response = "completed"
    ctx.tool_results = [{"result": {"path": "/tmp/main.py", "success": True}}]
    ctx.runtime_policy = {"feature_flags": {"upgrade_verify_mandatory_gates": True}}

    ctx = await StageVerify().run(ctx, _Agent())

    assert ctx.delivery_blocked is True
    assert ctx.qa_results.get("code_failure", {}).get("class") == "planning_failure"
    assert ctx.qa_results.get("code_recovery_strategy", {}).get("kind") == "quality_gate_plan"
    repair_plan = ctx.qa_results.get("code_repair_plan", {})
    assert repair_plan.get("stack") == "python"
    assert repair_plan.get("commands") == ["ruff check .", "python -m pytest -q", "mypy ."]
    assert "Quality gate next:" in (ctx.final_response or "")


@pytest.mark.asyncio
async def test_verify_stage_records_capability_runtime_and_repair_trace_for_screen():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.final_response = "✅ İşlem tamamlandı."
    ctx.tool_results = [
        {
            "status": "success",
            "artifacts": [{"path": "/tmp/screen.png", "type": "image"}],
            "raw": {
                "ui_map": {"frontmost_app": "Cursor", "running_apps": ["Cursor", "Safari"]},
                "ocr": "Cursor Safari",
                "screenshots": ["/tmp/screen.png"],
                "warning": "vision_timeout:9.0s",
            },
        }
    ]

    ctx = await StageVerify().run(ctx, _DummyAgent())

    runtime_payload = ctx.qa_results.get("capability_runtime", {})
    assert runtime_payload.get("verify", {}).get("ok") is True
    assert runtime_payload.get("repair", {}).get("strategy") == "screen_summary_synthesized"
    assert "Cursor" in (ctx.final_response or "")
    assert "screen_summary_synthesized" in list(ctx.telemetry.get("repair_steps", []) or [])
    assert "capability_runtime" in dict(ctx.telemetry.get("verifier_results", {}) or {})


@pytest.mark.asyncio
async def test_verify_stage_blocks_file_ops_when_runtime_contract_fails(tmp_path):
    target = tmp_path / "elyan-test"

    ctx = PipelineContext(user_input="masaüstünde elyan-test klasörü oluştur", user_id="u1", channel="cli")
    ctx.action = "create_folder"
    ctx.intent = {"action": "create_folder", "params": {"path": str(target)}}
    ctx.final_response = "İşlem tamamlandı."
    ctx.tool_results = []

    ctx = await StageVerify().run(ctx, _DummyAgent())

    runtime_payload = ctx.qa_results.get("capability_runtime", {})
    assert runtime_payload.get("verify", {}).get("ok") is False
    capability_failure = ctx.qa_results.get("capability_failure", {})
    assert capability_failure.get("class") in {"planning_failure", "tool_failure"}
    assert ctx.delivery_blocked is True
    assert any(err.startswith("capability:") for err in ctx.errors)


def test_completion_gate_fails_actionable_without_success_signals():
    ctx = PipelineContext(user_input="uygulamayi ac", user_id="u1", channel="cli")
    ctx.action = "open_app"
    ctx.final_response = "Islem tamamlandi."
    ctx.tool_results = []
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is False
    assert "no_successful_tool_result" in gate["failed"]


def test_completion_gate_passes_screen_with_summary_signal():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.final_response = "On planda Chrome acik gorunuyor."
    ctx.tool_results = [
        {
            "success": True,
            "observations": [{"summary": "On planda Chrome acik gorunuyor.", "stage": "before"}],
        }
    ]
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is True


def test_completion_gate_passes_screen_with_nested_raw_summary_signal():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.final_response = "✅ İşlem tamamlandı."
    ctx.tool_results = [
        {
            "status": "success",
            "message": "İşlem başarıyla tamamlandı.",
            "raw": {
                "success": True,
                "observations": [{"summary": "On planda Cursor acik gorunuyor.", "stage": "before"}],
            },
        }
    ]
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is True


def test_completion_gate_passes_screen_with_status_success_and_ui_map_signal():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.final_response = "✅ İşlem tamamlandı."
    ctx.tool_results = [
        {
            "status": "success",
            "artifacts": [{"path": "/tmp/screen.png", "type": "image"}],
            "raw": {
                "ui_map": {"frontmost_app": "Google Chrome", "running_apps": ["Google Chrome", "Cursor"]},
                "screenshots": ["/tmp/screen.png"],
            },
        }
    ]
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is True


def test_screen_completion_repair_synthesizes_summary_from_ui_map():
    ctx = PipelineContext(user_input="durum nedir", user_id="u1", channel="cli")
    ctx.action = "screen_workflow"
    ctx.final_response = "✅ İşlem tamamlandı."
    ctx.tool_results = [
        {
            "status": "success",
            "raw": {
                "ui_map": {"frontmost_app": "Cursor", "running_apps": ["Cursor", "Safari"]},
                "warning": "vision_timeout:9.0s",
            },
        }
    ]

    repair = _repair_screen_completion(ctx)
    assert repair["repaired"] is True
    assert "Cursor" in ctx.final_response
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is True


def test_completion_gate_passes_write_file_with_nested_raw_artifact_path():
    ctx = PipelineContext(user_input="masaüstüne not olarak sen kimsin yaz", user_id="u1", channel="cli")
    ctx.action = "write_file"
    ctx.final_response = "İşlem tamamlandı: /Users/emrekoca/Desktop/not.txt"
    ctx.tool_results = [
        {
            "status": "success",
            "result": {
                "raw": {
                    "path": "/Users/emrekoca/Desktop/not.txt",
                }
            },
        }
    ]
    gate = _evaluate_completion_gate(ctx)
    assert gate["ok"] is True


def test_screen_capability_realign_does_not_override_research_save_combo():
    should = _should_realign_to_capability(
        user_input="Safari aç köpekler araştır masaüstüne kaydet",
        action="open_app",
        capability_domain="screen_operator",
        capability_confidence=0.82,
        capability_primary_action="vision_operator_loop",
        intent_confidence=0.30,
        override_threshold=0.62,
    )
    assert should is False


def test_collect_paths_from_tool_results_reads_nested_outputs_and_artifacts():
    rows = [
        {
            "result": {
                "raw": {
                    "path": "/tmp/not.txt",
                    "outputs": ["/tmp/report.docx"],
                    "artifacts": [{"path": "/tmp/report.md"}],
                }
            }
        }
    ]
    assert collect_paths_from_tool_results(rows) == ["/tmp/not.txt", "/tmp/report.docx", "/tmp/report.md"]


@pytest.mark.asyncio
async def test_direct_intent_failure_text_falls_back_to_standard_chat():
    class _LLM:
        async def generate(self, prompt, **kwargs):
            _ = (prompt, kwargs)
            return "fallback chat response"

    class _ExecAgent:
        def __init__(self):
            self.llm = _LLM()

        def _should_run_direct_intent(self, intent, user_input):
            _ = (intent, user_input)
            return True

        async def _run_direct_intent(self, *args, **kwargs):
            _ = (args, kwargs)
            return "Hata: islem tamamlanamadi"

    ctx = PipelineContext(user_input="whatsapp kapat", user_id="u1", channel="cli")
    ctx.intent = {"action": "close_app", "params": {"app_name": "WhatsApp"}}
    ctx.action = "close_app"
    ctx.job_type = "communication"
    ctx.runtime_policy = {"feature_flags": {}}

    out = await StageExecute().run(ctx, _ExecAgent())
    assert "fallback chat response" in (out.final_response or "")
    assert any(str(err).startswith("direct_intent_failed:") for err in out.errors)


@pytest.mark.asyncio
async def test_deliver_stage_updates_runtime_trace_final_status():
    ctx = PipelineContext(user_input="selam", user_id="u1", channel="cli")
    ctx.final_response = "tamam"
    ctx.verified = True
    ctx.delivery_blocked = False

    out = await StageDeliver().run(ctx, _DummyAgent())
    assert out.telemetry.get("final_status") == "success"
    assert out.phase_records.get("deliver", {}).get("final_status") == "success"
