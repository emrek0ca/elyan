from pathlib import Path

import pytest

from core.personalization.adapters import AdapterArtifactStore, AdapterRegistry
from core.personalization.manager import PersonalizationManager
from core.personalization.memory import PersonalMemoryStore
from core.personalization.retrieval import MemoryIndexer, MemoryRetriever, MemoryReranker
from core.personalization.reward import PreferencePairBuilder, RewardEventStore, RewardService
from core.personalization.training import AdapterEvaluator, AdapterPromoter, AdapterTrainer, TrainerQueue


def test_personal_memory_retrieval_is_user_scoped(tmp_path):
    store = PersonalMemoryStore(storage_root=tmp_path / "memory", vector_backend="sqlite", graph_backend="sqlite")
    store.write_interaction(
        user_id="user-a",
        user_input="Bana kısa Python notları ver",
        assistant_output="Python notları burada",
        action="chat",
        success=True,
    )
    store.write_interaction(
        user_id="user-b",
        user_input="React landing page tasarla",
        assistant_output="Landing page planı burada",
        action="create_web_project_scaffold",
        success=True,
    )

    result = store.retrieve_context("user-a", "Python notları", k=3, token_budget=256)

    assert result["interaction_count"] == 1
    assert result["vector_hits"]
    assert all("React landing page tasarla" != hit["user_input"] for hit in result["vector_hits"])
    assert "React landing page tasarla" not in result["text"]


def test_adapter_binding_local_vs_cloud_and_missing_artifact(tmp_path):
    store = AdapterArtifactStore(storage_root=tmp_path / "adapters")
    registry = AdapterRegistry(store, max_hot=2)
    candidate = store.create_candidate_adapter(
        "user-a",
        "ollama:llama3",
        strategy="hybrid",
        metrics={"interaction_count": 5},
    )
    promoted = store.promote_version("user-a", "ollama:llama3", candidate["adapter_version"])
    assert promoted is not None

    local_binding = registry.resolve_binding("user-a", "ollama:llama3", "ollama")
    cloud_binding = registry.resolve_binding("user-a", "ollama:llama3", "openai")

    assert local_binding["status"] == "ready"
    assert local_binding["state"] == "warm"
    assert cloud_binding["state"] == "none"
    assert cloud_binding["reason"] == "memory_only_provider"

    Path(local_binding["adapter_path"]).unlink()
    missing_binding = registry.resolve_binding("user-a", "ollama:llama3", "ollama")
    assert missing_binding["status"] == "fallback_base_model"
    assert missing_binding["reason"] == "missing_artifact"


def test_reward_service_ignores_unsafe_negative_implicit_signals(tmp_path):
    reward = RewardService(storage_root=tmp_path / "reward")

    delete_event = reward.record_feedback(user_id="user-a", interaction_id="i1", event_type="delete")
    short_event = reward.record_feedback(user_id="user-a", interaction_id="i1", event_type="short_dwell")

    assert delete_event["reward"] == 0.0
    assert short_event["reward"] == 0.0
    assert delete_event["ignored_negative"] is True
    assert short_event["ignored_negative"] is True


def test_memory_retriever_and_reranker_return_user_scoped_hits(tmp_path):
    store = PersonalMemoryStore(storage_root=tmp_path / "memory", vector_backend="sqlite", graph_backend="sqlite")
    indexer = MemoryIndexer(store)
    retriever = MemoryRetriever(store, MemoryReranker())
    indexer.index_interaction(
        user_id="user-a",
        user_input="Python için kısa not çıkar",
        assistant_output="Python notları hazır",
        action="chat",
        success=True,
    )
    indexer.index_interaction(
        user_id="user-b",
        user_input="React landing page hazırla",
        assistant_output="Landing page taslağı hazır",
        action="code",
        success=True,
    )

    result = retriever.retrieve("Python not", "user-a", 256, k=3)

    assert result["vector_hits"]
    assert result["vector_hits"][0]["user_input"] == "Python için kısa not çıkar"
    assert all("React landing page hazırla" != hit["user_input"] for hit in result["vector_hits"])


def test_reward_event_store_and_preference_pair_builder(tmp_path):
    reward = RewardService(storage_root=tmp_path / "reward")
    event_store = RewardEventStore(reward)
    builder = PreferencePairBuilder()

    event = event_store.record(
        user_id="user-a",
        interaction_id="i-1",
        event_type="accepted_edit",
        metadata={
            "edit_distance": 0.1,
            "chosen_response": "Kısa özet",
            "rejected_response": "Uzun cevap",
        },
    )
    pair = builder.build(
        user_id="user-a",
        interaction_id="i-1",
        metadata={"chosen_response": "Kısa özet", "rejected_response": "Uzun cevap"},
    )

    assert event["event"]["event_type"] == "accepted_edit"
    assert event["preference_pair"]["chosen_response"] == "Kısa özet"
    assert pair is not None
    assert pair.rejected_response == "Uzun cevap"


def test_trainer_queue_respects_threshold_and_promotes_candidate(tmp_path):
    memory = PersonalMemoryStore(storage_root=tmp_path / "memory", vector_backend="sqlite", graph_backend="sqlite")
    reward = RewardService(storage_root=tmp_path / "reward")
    artifacts = AdapterArtifactStore(storage_root=tmp_path / "adapters")
    trainer = AdapterTrainer(memory_store=memory, reward_service=reward, artifact_store=artifacts)
    evaluator = AdapterEvaluator(memory_store=memory, reward_service=reward, min_examples=2, min_feedback_events=1)
    queue = TrainerQueue(
        memory_store=memory,
        reward_service=reward,
        artifact_store=artifacts,
        trainer=trainer,
        evaluator=evaluator,
        storage_root=tmp_path / "queue",
        min_examples=2,
        cooldown_minutes=0,
    )

    memory.write_interaction(user_id="user-a", user_input="ilk", assistant_output="cevap", action="chat", success=True)
    reward.record_feedback(user_id="user-a", interaction_id="i1", event_type="like")
    preview = queue.preview_training_decision("user-a", "ollama:llama3")
    assert preview["eligible"] is False
    assert preview["reason"] == "below_min_examples"

    memory.write_interaction(user_id="user-a", user_input="ikinci", assistant_output="cevap 2", action="chat", success=True)
    queued = queue.enqueue_user_update(user_id="user-a", base_model_id="ollama:llama3", strategy="hybrid")
    assert queued["queued"] is True

    ran = queue.run_once()
    assert ran["ran"] is True
    assert ran["status"] == "promoted"
    active = artifacts.resolve_active_metadata("user-a", "ollama:llama3")
    assert active is not None
    assert active["status"] == "ready"


def test_adapter_promoter_wraps_artifact_promotion(tmp_path):
    artifacts = AdapterArtifactStore(storage_root=tmp_path / "adapters")
    promoter = AdapterPromoter(artifacts)
    candidate = artifacts.create_candidate_adapter(
        "user-a",
        "ollama:llama3",
        strategy="hybrid",
        metrics={"interaction_count": 4},
    )

    promoted = promoter.promote("user-a", "ollama:llama3", candidate["adapter_version"])

    assert promoted is not None
    assert promoted["status"] == "ready"


@pytest.mark.asyncio
async def test_personalization_manager_runs_memory_feedback_training_and_delete(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path))
    manager = PersonalizationManager(
        config={
            "enabled": True,
            "mode": "hybrid",
            "vector_backend": "sqlite",
            "graph_backend": "sqlite",
            "training": {"min_examples": 2, "cooldown_minutes": 0},
            "adapters": {"cache": {"max_hot": 4}, "storage_root": str(tmp_path / "adapters")},
            "retrieval": {"top_k": 3, "max_context_tokens": 256},
        }
    )

    cloud_context = await manager.get_runtime_context(
        "user-a",
        {"request": "Bana araştırma özeti ver", "provider": "openai", "model": "gpt-4o", "base_model_id": "openai:gpt-4o"},
    )
    assert cloud_context["adapter_binding"]["state"] == "none"
    assert cloud_context["adapter_binding"]["reason"] == "memory_only_provider"

    first = manager.record_interaction(
        user_id="user-a",
        user_input="Python ile kısa bir özet çıkar",
        assistant_output="İşte Python özeti",
        action="chat",
        success=True,
        metadata={"provider": "ollama", "model": "llama3", "base_model_id": "ollama:llama3"},
    )
    manager.record_interaction(
        user_id="user-a",
        user_input="Aynı tonda devam et",
        assistant_output="Aynı tonda devam ediyorum",
        action="chat",
        success=True,
        metadata={"provider": "ollama", "model": "llama3", "base_model_id": "ollama:llama3"},
    )
    feedback = manager.record_feedback(
        user_id="user-a",
        interaction_id=first["interaction_id"],
        event_type="accepted_edit",
        metadata={
            "edit_distance": 0.1,
            "provider": "ollama",
            "model": "llama3",
            "base_model_id": "ollama:llama3",
            "chosen_response": "İşte Python özeti",
            "rejected_response": "Uzun ve dağınık çıktı",
        },
    )
    assert feedback["training_job"]["queued"] is True

    ran = manager.trainer_queue.run_once()
    assert ran["status"] == "promoted"

    local_context = await manager.get_runtime_context(
        "user-a",
        {"request": "Python özeti tekrar ver", "provider": "ollama", "model": "llama3", "base_model_id": "ollama:llama3"},
    )
    assert local_context["adapter_binding"]["status"] == "ready"
    assert local_context["retrieved_memory_context"]
    assert local_context["runtime_profile"]["preferred_language"]

    deleted = manager.delete_user_data("user-a")
    assert deleted["memory"]["deleted_interactions"] >= 2
    assert deleted["reward"]["deleted_feedback_events"] >= 1
    assert deleted["adapters"]["deleted_versions"] >= 1
    assert manager.memory_store.interaction_count("user-a") == 0
    assert manager.reward_service.aggregate_user_feedback("user-a")["feedback_events"] == 0
