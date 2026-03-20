from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.ml import get_action_ranker, get_clarification_classifier, get_intent_scorer, get_model_runtime, get_verifier
from core.pipeline import PipelineContext, StageVerify


def test_model_runtime_reports_fallback_capabilities_without_torch_stack():
    runtime = get_model_runtime()
    snapshot = runtime.snapshot()

    assert snapshot["enabled"] is True
    assert snapshot["execution_mode"] == "local_first"
    assert snapshot["capabilities"]["embedding"]["available"] is True
    assert snapshot["capabilities"]["embedding"]["fallback"] in {True, False}
    assert snapshot["capabilities"]["adapter_runtime"]["backend"] in {"heuristic_fallback", "peft_lora"}


def test_intent_scorer_low_confidence_requests_produce_clarify_or_fallback():
    scorer = get_intent_scorer()
    result = scorer.score("şuna bir bakar mısın")

    assert result["confidence"] <= 0.55
    assert result["advisory"] in {"clarify", "fallback"}


def test_action_ranker_prefers_intent_match():
    ranker = get_action_ranker()
    ranked = ranker.rank({"label": "code"}, ["research", "code", "browser"], {})

    assert ranked[0]["candidate"] == "code"
    assert ranked[0]["selected"] is True


def test_verifier_penalizes_missing_artifacts_for_file_task():
    verifier = get_verifier()
    result = verifier.score({"kind": "file"}, {"status": "success", "text": "tamam"}, [])

    assert result["ok"] is False
    assert "missing_required_artifact" in result["reasons"]


@pytest.mark.asyncio
async def test_stage_verify_records_ml_verifier():
    ctx = PipelineContext(user_input="dosyayı kaydet", user_id="u1", channel="cli")
    ctx.job_type = "file"
    ctx.action = "write_file"
    ctx.final_response = "Dosya yazıldı"
    ctx.tool_results = [{"tool": "write_file", "status": "success", "artifacts": [{"path": "/tmp/out.txt"}]}]
    ctx.runtime_policy = {}

    class _Agent:
        verifier_service = get_verifier()
        llm = None

    out = await StageVerify().run(ctx, _Agent())

    assert "ml_verifier" in out.qa_results
    assert isinstance(out.phase_records.get("verify", {}).get("ml_verifier"), dict)
