from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.ml import get_action_ranker, get_clarification_classifier, get_intent_scorer, get_model_runtime, get_verifier
from core.pipeline import PipelineContext, StageVerify


def _build_model_runtime(monkeypatch: pytest.MonkeyPatch, environment: dict[str, object], modules: dict[str, bool]):
    from core.ml.runtime import ModelRuntime

    fake_manager = SimpleNamespace(snapshot=lambda: {"environment": environment})
    monkeypatch.setattr("core.ml.runtime.get_model_manager", lambda: fake_manager)
    monkeypatch.setattr(ModelRuntime, "_module_matrix", lambda self: modules)
    return ModelRuntime()


@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "embedding fallback",
            "environment": {
                "backend": "local_hashing",
                "device": "cpu_fallback",
                "torch_available": False,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": False,
                "sentence_transformers": False,
                "transformers": False,
                "peft": False,
                "trl": False,
            },
            "kind": "embedding",
            "expected": {
                "available": True,
                "backend": "local_hashing",
                "fallback": True,
                "fallback_mode": "deterministic",
            },
        },
        {
            "name": "embedding torch stack",
            "environment": {
                "backend": "torch",
                "device": "cpu",
                "torch_available": True,
                "sentence_transformers_available": True,
            },
            "modules": {
                "torch": True,
                "sentence_transformers": True,
                "transformers": True,
                "peft": True,
                "trl": True,
            },
            "kind": "embedding",
            "expected": {
                "available": True,
                "backend": "torch",
                "fallback": False,
                "fallback_mode": "native",
            },
        },
        {
            "name": "intent encoder with transformers",
            "environment": {
                "backend": "torch",
                "device": "cpu",
                "torch_available": True,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": True,
                "sentence_transformers": False,
                "transformers": True,
                "peft": False,
                "trl": False,
            },
            "kind": "intent_encoder",
            "expected": {
                "available": True,
                "backend": "distilled_classifier",
                "fallback": False,
                "fallback_mode": "native",
            },
        },
        {
            "name": "reranker lexical fallback",
            "environment": {
                "backend": "local_hashing",
                "device": "cpu_fallback",
                "torch_available": False,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": False,
                "sentence_transformers": False,
                "transformers": False,
                "peft": False,
                "trl": False,
            },
            "kind": "reranker",
            "expected": {
                "available": False,
                "backend": "lexical_reranker",
                "fallback": True,
                "fallback_mode": "lexical",
            },
        },
        {
            "name": "reranker semantic backend",
            "environment": {
                "backend": "torch",
                "device": "cpu",
                "torch_available": True,
                "sentence_transformers_available": True,
            },
            "modules": {
                "torch": True,
                "sentence_transformers": True,
                "transformers": False,
                "peft": False,
                "trl": False,
            },
            "kind": "reranker",
            "expected": {
                "available": True,
                "backend": "semantic_reranker",
                "fallback": False,
                "fallback_mode": "semantic",
            },
        },
        {
            "name": "reward model heuristic fallback",
            "environment": {
                "backend": "local_hashing",
                "device": "cpu_fallback",
                "torch_available": False,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": False,
                "sentence_transformers": False,
                "transformers": True,
                "peft": False,
                "trl": False,
            },
            "kind": "reward_model",
            "expected": {
                "available": False,
                "backend": "heuristic_scorer",
                "fallback": True,
                "fallback_mode": "heuristic",
            },
        },
        {
            "name": "reward model trl backend",
            "environment": {
                "backend": "torch",
                "device": "cpu",
                "torch_available": True,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": True,
                "sentence_transformers": False,
                "transformers": True,
                "peft": False,
                "trl": True,
            },
            "kind": "reward_model",
            "expected": {
                "available": True,
                "backend": "trl_reward_model",
                "fallback": False,
                "fallback_mode": "native",
            },
        },
        {
            "name": "adapter runtime fallback",
            "environment": {
                "backend": "local_hashing",
                "device": "cpu_fallback",
                "torch_available": False,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": False,
                "sentence_transformers": False,
                "transformers": False,
                "peft": False,
                "trl": False,
            },
            "kind": "adapter_runtime",
            "expected": {
                "available": False,
                "backend": "heuristic_fallback",
                "fallback": True,
                "fallback_mode": "heuristic",
            },
        },
        {
            "name": "adapter runtime peft backend",
            "environment": {
                "backend": "torch",
                "device": "cpu",
                "torch_available": True,
                "sentence_transformers_available": False,
            },
            "modules": {
                "torch": True,
                "sentence_transformers": False,
                "transformers": False,
                "peft": True,
                "trl": False,
            },
            "kind": "adapter_runtime",
            "expected": {
                "available": True,
                "backend": "peft_lora",
                "fallback": False,
                "fallback_mode": "native",
            },
        },
    ],
    ids=lambda case: case["name"],
)
def test_model_runtime_capability_matrix(monkeypatch: pytest.MonkeyPatch, case: dict[str, object]):
    runtime = _build_model_runtime(
        monkeypatch,
        case["environment"],
        case["modules"],
    )

    capability = runtime.get_capability(case["kind"])
    snapshot = runtime.snapshot()

    assert capability["available"] is case["expected"]["available"]
    assert capability["backend"] == case["expected"]["backend"]
    assert capability["fallback"] is case["expected"]["fallback"]
    assert capability["metadata"]["fallback_mode"] == case["expected"]["fallback_mode"]
    for name, value in case["modules"].items():
        assert snapshot["dependencies"][name] is value
    assert snapshot["capabilities"][case["kind"]]["metadata"]["dependency_status"]
    if case["kind"] == "embedding":
        assert snapshot["capabilities"][case["kind"]]["metadata"]["dependency_status"] == {
            "torch": case["environment"]["torch_available"],
            "sentence_transformers": case["environment"]["sentence_transformers_available"],
        }
    elif case["kind"] == "reranker":
        assert snapshot["capabilities"][case["kind"]]["metadata"]["dependency_status"] == {
            "sentence_transformers": case["modules"]["sentence_transformers"],
            "transformers": case["modules"]["transformers"],
        }
    elif case["kind"] == "reward_model":
        assert snapshot["capabilities"][case["kind"]]["metadata"]["dependency_status"] == {
            "transformers": case["modules"]["transformers"],
            "trl": case["modules"]["trl"],
        }
    elif case["kind"] == "adapter_runtime":
        assert snapshot["capabilities"][case["kind"]]["metadata"]["dependency_status"] == {
            "torch": case["modules"]["torch"],
            "peft": case["modules"]["peft"],
        }


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
