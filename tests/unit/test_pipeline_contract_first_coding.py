from __future__ import annotations

import pytest

from core.pipeline import PipelineContext, StageExecute


def _contract(adapter_id: str = "python_app", supported: bool = True) -> dict:
    return {
        "contract_id": "contract_1",
        "adapter_id": adapter_id,
        "repo_type": "python",
        "supported": supported,
        "required_gates": ["test"],
        "claim_policy": {"require_evidence": True, "require_verified_gates": True},
        "failure_envelope": {"code": "unsupported_stack", "reason": "desteklenmeyen stack"} if not supported else {},
    }


@pytest.mark.asyncio
async def test_stage_execute_uses_contract_first_runtime_branch():
    class _Agent:
        def __init__(self):
            self._last_runtime_task_spec_payload = None

        async def _run_runtime_task_spec(self, task_spec, *, user_input):
            _ = (task_spec, user_input)
            self._last_runtime_task_spec_payload = {
                "success": True,
                "artifact_paths": ["/tmp/main.py"],
                "message": "patched",
            }
            return "patched"

    ctx = PipelineContext(user_input="python kodunu düzelt", user_id="u1", channel="cli")
    ctx.job_type = "code_project"
    ctx.action = "edit_text_file"
    ctx.is_code_job = True
    ctx.intent = {"task_spec": {"task_id": "spec_1"}}
    ctx.coding_contract = _contract()
    ctx.runtime_policy = {"execution": {"mode": "operator"}, "metadata": {}}

    out = await StageExecute().run(ctx, _Agent())

    assert out.final_response == "patched"
    assert out.tool_results[0]["source"] == "contract_first_runtime"
    assert out.tool_results[0]["artifact_paths"] == ["/tmp/main.py"]


@pytest.mark.asyncio
async def test_stage_execute_uses_contract_first_greenfield_branch_for_project_creation():
    class _Agent:
        def __init__(self):
            self._last_direct_intent_payload = None

        def _ensure_llm(self):
            return True

        async def _llm_build_project(self, **kwargs):
            _ = kwargs
            self._last_direct_intent_payload = {
                "success": True,
                "project_dir": "/tmp/cat-site",
                "artifact_paths": ["/tmp/cat-site"],
                "message": "project created",
            }
            return dict(self._last_direct_intent_payload)

    ctx = PipelineContext(user_input="kedi sitesi yap", user_id="u1", channel="cli")
    ctx.job_type = "code_project"
    ctx.action = "create_coding_project"
    ctx.is_code_job = True
    ctx.intent = {"action": "create_coding_project", "params": {"project_name": "cat-site"}}
    ctx.coding_contract = _contract(adapter_id="vanilla_web")
    ctx.runtime_policy = {"execution": {"mode": "operator"}, "metadata": {}}

    out = await StageExecute().run(ctx, _Agent())

    assert out.final_response == "project created"
    assert out.tool_results[0]["source"] == "contract_first_greenfield"
    assert out.tool_results[0]["raw"]["project_dir"] == "/tmp/cat-site"


@pytest.mark.asyncio
async def test_stage_execute_blocks_greenfield_payload_with_error_text():
    class _Agent:
        def __init__(self):
            self._last_direct_intent_payload = None

        def _ensure_llm(self):
            return True

        async def _llm_build_project(self, **kwargs):
            _ = kwargs
            self._last_direct_intent_payload = {
                "success": True,
                "project_dir": "/tmp/cat-site",
                "artifact_paths": ["/tmp/cat-site"],
                "message": "Canonical greenfield üretim hata verdi: [Errno 21] Is a directory",
            }
            return dict(self._last_direct_intent_payload)

    ctx = PipelineContext(user_input="kedi sitesi yap", user_id="u1", channel="cli")
    ctx.job_type = "code_project"
    ctx.action = "create_coding_project"
    ctx.is_code_job = True
    ctx.intent = {"action": "create_coding_project", "params": {"project_name": "cat-site"}}
    ctx.coding_contract = _contract(adapter_id="vanilla_web")
    ctx.runtime_policy = {"execution": {"mode": "operator"}, "metadata": {}}

    out = await StageExecute().run(ctx, _Agent())

    assert out.tool_results[0]["success"] is False
    assert out.tool_results[0]["error_code"] == "unsupported_or_unverified_generation"
    assert "hata verdi" in out.final_response.lower()


@pytest.mark.asyncio
async def test_stage_execute_blocks_unsupported_contract_first_stack():
    ctx = PipelineContext(user_input="legacy cobol projeyi düzelt", user_id="u1", channel="cli")
    ctx.job_type = "code_project"
    ctx.action = "edit_text_file"
    ctx.is_code_job = True
    ctx.coding_contract = _contract(supported=False)
    ctx.runtime_policy = {"execution": {"mode": "operator"}, "metadata": {}}

    out = await StageExecute().run(ctx, object())

    assert out.delivery_blocked is True
    assert out.claim_blocked_reason == "unsupported_stack"
    assert "desteklenmeyen stack" in out.final_response
