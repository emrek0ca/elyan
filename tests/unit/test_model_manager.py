from __future__ import annotations

import numpy as np
import pytest

from core.model_manager import (
    FALLBACK_EMBEDDING_DIMENSION,
    LocalHashingEmbedder,
    ModelManager,
    ModelSpec,
    get_model_manager,
    get_shared_embedder,
)


def test_local_hashing_embedder_is_deterministic() -> None:
    embedder = LocalHashingEmbedder(dimension=96)

    first = embedder.encode("PyTorch roadmap", normalize_embeddings=True)
    second = embedder.encode("PyTorch roadmap", normalize_embeddings=True)

    assert isinstance(first, np.ndarray)
    assert first.shape == (96,)
    assert np.allclose(first, second)


@pytest.mark.asyncio
async def test_shared_embedder_falls_back_when_torch_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = get_model_manager()
    manager.clear_cache()

    monkeypatch.setattr(manager._environment, "torch_available", False)
    monkeypatch.setattr(manager._environment, "sentence_transformers_available", False)
    monkeypatch.setattr(manager._environment, "backend", "local_hashing")
    monkeypatch.setattr(manager._environment, "device", "cpu_fallback")

    embedder = await get_shared_embedder()

    assert isinstance(embedder, LocalHashingEmbedder)
    assert embedder.get_sentence_embedding_dimension() == FALLBACK_EMBEDDING_DIMENSION

    vectors = embedder.encode(["PyTorch", "FAISS"], normalize_embeddings=True)
    assert isinstance(vectors, np.ndarray)
    assert vectors.shape == (2, FALLBACK_EMBEDDING_DIMENSION)
    assert not np.allclose(vectors[0], vectors[1])

    snapshot = manager.snapshot()
    assert snapshot["active_model_count"] == 1
    assert snapshot["environment"]["torch_available"] is False
    assert snapshot["environment"]["cached_models"][0]["backend"] == "local_hashing"


@pytest.mark.asyncio
async def test_registered_model_is_cached_until_unloaded() -> None:
    manager = ModelManager()
    manager.clear_cache()

    call_count = {"value": 0}

    class DummyEmbedder:
        backend = "unit_test"
        device = "cpu"

        def encode(self, sentences, **_kwargs):
            if isinstance(sentences, str):
                return np.ones(16, dtype=np.float32)
            return np.ones((len(sentences), 16), dtype=np.float32)

    def loader() -> DummyEmbedder:
        call_count["value"] += 1
        return DummyEmbedder()

    manager.register_model(
        "unit:test-embedder",
        loader=loader,
        spec=ModelSpec(
            name="unit:test-embedder",
            kind="embedding",
            cacheable=True,
        ),
    )

    first = await manager.get_embedding_model("unit:test-embedder")
    second = await manager.get_embedding_model("unit:test-embedder")
    assert first is second
    assert call_count["value"] == 1

    manager.unload_model("unit:test-embedder")
    third = await manager.get_embedding_model("unit:test-embedder")

    assert call_count["value"] == 2
    assert third is not first


@pytest.mark.asyncio
async def test_benchmark_reports_phase0_thresholds_and_dimensions() -> None:
    manager = ModelManager()
    manager.clear_cache()

    manager.register_model(
        "unit:benchmark-embedder",
        loader=lambda: LocalHashingEmbedder(dimension=128),
        spec=ModelSpec(
            name="unit:benchmark-embedder",
            kind="embedding",
            cacheable=True,
            metadata={"purpose": "phase0-benchmark"},
        ),
    )

    report = await manager.benchmark_model(
        "unit:benchmark-embedder",
        sample_texts=[
            "PyTorch framework validation.",
            "Shared embedder smoke test.",
            "Elyan phase zero benchmark.",
        ],
        force_reload=True,
    )

    assert report["model_name"] == "unit:benchmark-embedder"
    assert report["vector_dimension"] == 128
    assert report["sample_count"] == 3
    assert report["passed"] is True
    assert report["load_seconds"] >= 0
    assert report["encode_seconds"] >= 0
    assert report["thresholds"]["load_seconds"] == 3.0
    assert report["thresholds"]["idle_memory_mb"] == 2048.0


def test_wrapper_reexports_canonical_manager() -> None:
    import bot.core.model_manager as nested
    import core.model_manager as canonical

    assert nested.ModelManager is canonical.ModelManager
    assert nested.get_shared_embedder is canonical.get_shared_embedder
