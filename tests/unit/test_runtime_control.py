from __future__ import annotations

import pytest

from core.device_sync import DeviceSyncStore
from core.reliability.store import OutcomeStore
from core.runtime_control import RuntimeControlPlane


class _LearningControl:
    async def get_runtime_context(self, user_id, request_meta=None):
        _ = request_meta
        return {
            "runtime_profile": {"preferred_language": "tr"},
            "retrieved_memory_context": "Eski tercih: kisa cevap",
            "retrieved_memory": {"vector_hits": []},
            "adapter_binding": {"status": "ready", "state": "warm"},
            "reward_policy": {"policy": "explicit_safe_implicit"},
            "training_decision": {"eligible": False},
            "provider": "ollama",
            "model": "llama3",
            "base_model_id": "ollama:llama3",
            "request_prompt": f"[Current Request]\n{request_meta.get('request')}",
        }


class _ModelRuntime:
    def snapshot(self):
        return {"enabled": True, "execution_mode": "local_first"}


class _IntentScorer:
    def __init__(self, label: str, confidence: float):
        self.label = label
        self.confidence = confidence

    def score(self, *_args, **_kwargs):
        return {
            "label": self.label,
            "confidence": self.confidence,
            "raw_confidence": self.confidence,
            "source": "test",
            "advisory": "execute" if self.confidence >= 0.68 else "clarify",
            "should_clarify": self.confidence < 0.55,
        }


class _ActionRanker:
    def rank(self, _intent, candidates, _context):
        normalized = [str(item).strip().lower() for item in candidates if str(item).strip()]
        return [{"candidate": normalized[0], "score": 0.92, "reasons": ["test"], "selected": True}] if normalized else []


class _Clarifier:
    def __init__(self, should_clarify: bool):
        self.should_clarify = should_clarify

    def classify(self, *_args, **_kwargs):
        return {
            "decision": "clarify" if self.should_clarify else "proceed",
            "should_clarify": self.should_clarify,
            "confidence": 0.82 if self.should_clarify else 0.24,
            "reasons": ["test"],
        }


@pytest.mark.asyncio
async def test_runtime_control_prepares_fast_direct_action_and_records_sync(tmp_path):
    outcome_store = OutcomeStore(storage_root=tmp_path / "reliability")
    sync_store = DeviceSyncStore(storage_root=tmp_path / "sync")
    plane = RuntimeControlPlane(
        learning_control=_LearningControl(),
        model_runtime=_ModelRuntime(),
        intent_scorer=_IntentScorer("file", 0.91),
        action_ranker=_ActionRanker(),
        clarification_classifier=_Clarifier(False),
        outcome_store=outcome_store,
        sync_store=sync_store,
    )

    result = await plane.prepare_turn(
        request_id="req-fast",
        user_id="u1",
        request="Masaustune note.txt yaz",
        channel="dashboard",
        provider="ollama",
        model="llama3",
        base_model_id="ollama:llama3",
        metadata={"device_id": "iphone", "session_id": "sess-1"},
    )

    decisions = outcome_store.decisions_for_request("req-fast")
    snapshot = sync_store.get_user_snapshot("u1")

    assert result["request_class"] == "direct_action"
    assert result["execution_path"] == "fast"
    assert result["latency_budget_ms"] == 800
    assert result["personalization"]["adapter_binding"]["status"] == "ready"
    assert any(item["kind"] == "request_class" and item["selected"] == "direct_action" for item in decisions)
    assert snapshot["devices"][0]["device_id"] == "iphone"
    assert snapshot["requests"][0]["execution_path"] == "fast"


@pytest.mark.asyncio
async def test_runtime_control_for_ambiguous_request_uses_deep_path(tmp_path):
    plane = RuntimeControlPlane(
        learning_control=_LearningControl(),
        model_runtime=_ModelRuntime(),
        intent_scorer=_IntentScorer("unknown", 0.31),
        action_ranker=_ActionRanker(),
        clarification_classifier=_Clarifier(True),
        outcome_store=OutcomeStore(storage_root=tmp_path / "reliability"),
        sync_store=DeviceSyncStore(storage_root=tmp_path / "sync"),
    )

    result = await plane.prepare_turn(
        request_id="req-deep",
        user_id="u2",
        request="sunla ilgilenir misin",
        channel="cli",
        provider="openai",
        model="gpt-4o",
        base_model_id="openai:gpt-4o",
    )

    assert result["execution_path"] == "deep"
    assert result["clarification_policy"]["decision"] == "clarify"
