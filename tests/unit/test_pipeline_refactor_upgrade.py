from __future__ import annotations

from types import SimpleNamespace

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
from core.pipeline_upgrade.verifier import enforce_output_contract, verify_code_gates, verify_asset_gates, build_critic_review_prompt


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
