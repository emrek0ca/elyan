from __future__ import annotations

from pathlib import Path

import pytest

from core.learning_engine import LearningEngine
from core.phase4_pipeline import Phase4Pipeline, Phase4Sample
from core.training_system import ChildLearningModel, TrainingExample


def _samples() -> list[Phase4Sample]:
    return [
        Phase4Sample(
            input_text="pytorch hakkında araştırma yap",
            intent="research",
            output_text="PyTorch mimarisini, eğitim akışını ve deployment seçeneklerini incele.",
            source="seed",
            confidence=1.0,
        ),
        Phase4Sample(
            input_text="landing page üret",
            intent="website",
            output_text="Tek sayfa, modern bir landing page oluştur.",
            source="seed",
            confidence=1.0,
        ),
        Phase4Sample(
            input_text="excel tablosu hazırla",
            intent="spreadsheet",
            output_text="Temiz bir Excel tablosu oluştur ve formatla.",
            source="seed",
            confidence=1.0,
        ),
        Phase4Sample(
            input_text="sunum hazırla",
            intent="presentation",
            output_text="Kurumsal bir sunum deck'i hazırla.",
            source="seed",
            confidence=1.0,
        ),
    ]


def test_collect_training_examples_merges_feedback_and_learning_engine(tmp_path: Path) -> None:
    training_system = ChildLearningModel(tmp_path / "training.db")
    training_system.feedback_loop.record_correction(
        user_input="pytoch araştır",
        bot_output="Wrong",
        correct_output="PyTorch araştırması yap",
        intent="research",
    )
    training_system.learn_from_example(
        TrainingExample(
            input_text="landing page oluştur",
            expected_output="Modern landing page üret",
            intent="website",
            success=True,
            timestamp=1.0,
            confidence=0.95,
        )
    )

    learning_engine = LearningEngine("phase4-user", storage_path=str(tmp_path / "learning"))
    learning_engine.record_interaction(
        "search",
        {"query": "pytorch"},
        {"result": "docs"},
        success=False,
        duration=0.2,
    )

    pipeline = Phase4Pipeline(storage_root=tmp_path / "phase4")
    samples = pipeline.collect_training_examples(
        training_system=training_system,
        learning_engine=learning_engine,
        limit=20,
    )

    assert samples
    assert any(sample.source == "feedback_loop" for sample in samples)
    assert any(sample.source == "knowledge_base" for sample in samples)
    assert any(sample.source == "learning_engine" for sample in samples)


def test_run_end_to_end_creates_bundle_and_deploys(tmp_path: Path) -> None:
    pipeline = Phase4Pipeline(storage_root=tmp_path / "phase4")
    run = pipeline.run_end_to_end(
        model_id="intent_router",
        name="Intent Router",
        base_model="local-proto",
        samples=_samples(),
        version="v1.0.0",
        deploy=True,
        export_onnx=True,
        build_bundle=True,
        benchmark=True,
    )

    assert run.model_id == "intent_router"
    assert run.version == "v1.0.0"
    assert run.samples == len(_samples())
    assert run.bundle is not None
    assert run.benchmark is not None
    assert run.health is not None
    assert run.status in {"success", "degraded"}

    bundle_root = Path(run.bundle["root"])
    assert bundle_root.exists()
    assert Path(run.bundle["manifest_path"]).exists()
    assert Path(run.bundle["model_path"]).exists()
    assert Path(run.bundle["dockerfile_path"]).exists()
    assert Path(run.bundle["compose_path"]).exists()
    assert Path(run.bundle["health_path"]).exists()
    assert Path(run.bundle["ci_path"]).exists()
    assert Path(run.bundle["model_card_path"]).exists()
    assert run.bundle["size_bytes"] > 0

    version = pipeline.framework.registry.get_model_version("intent_router", "v1.0.0")
    assert version is not None
    assert "intent_router" in pipeline.framework.deployer.get_deployed_models()
    assert run.benchmark["latency_ms"] >= 0
    assert run.metrics["accuracy"] >= 0.0
    assert run.metrics["macro_f1"] >= 0.0
    assert run.metrics["onnx_exported"] in {True, False}
    assert run.health["status"] in {"healthy", "degraded", "unknown"}


def test_export_onnx_package_falls_back_cleanly(tmp_path: Path) -> None:
    pipeline = Phase4Pipeline(storage_root=tmp_path / "phase4")
    run = pipeline.run_end_to_end(
        model_id="intent_router",
        name="Intent Router",
        base_model="local-proto",
        samples=_samples(),
        version="v1.0.0",
        deploy=False,
        export_onnx=False,
        build_bundle=False,
        benchmark=False,
    )

    model = pipeline._load_model("intent_router", "v1.0.0")
    report = pipeline.export_onnx_package("intent_router", "v1.0.0", model=model)

    assert report["status"] == "fallback"
    assert Path(report["manifest_path"]).exists()
    assert any(Path(path).exists() for path in report["artifacts"])
    assert run.status in {"success", "degraded"}


def test_ab_variant_selection_and_version_comparison(tmp_path: Path) -> None:
    pipeline = Phase4Pipeline(storage_root=tmp_path / "phase4")
    pipeline.run_end_to_end(
        model_id="intent_router",
        name="Intent Router",
        base_model="local-proto",
        samples=_samples(),
        version="v1.0.0",
        deploy=False,
        export_onnx=False,
        build_bundle=False,
        benchmark=False,
    )
    alt_samples = [
        Phase4Sample("dosya oluştur", "file", "Yeni dosya oluştur.", source="seed", confidence=1.0),
        Phase4Sample("dosyayı sil", "file", "Dosyayı sil.", source="seed", confidence=1.0),
        Phase4Sample("klasör listele", "file", "Klasör içeriğini göster.", source="seed", confidence=1.0),
        Phase4Sample("repo yaz", "code", "Kod üret.", source="seed", confidence=1.0),
    ]
    pipeline.run_end_to_end(
        model_id="intent_router",
        name="Intent Router",
        base_model="local-proto",
        samples=alt_samples,
        version="v2.0.0",
        deploy=False,
        export_onnx=False,
        build_bundle=False,
        benchmark=False,
    )

    choice_1 = pipeline.select_variant("phase4_ab", "user-123", ["v1.0.0", "v2.0.0"])
    choice_2 = pipeline.select_variant("phase4_ab", "user-123", ["v1.0.0", "v2.0.0"])
    assert choice_1 == choice_2
    assert choice_1 in {"v1.0.0", "v2.0.0"}

    comparison = pipeline.compare_versions(
        "intent_router",
        "v1.0.0",
        "v2.0.0",
        validation_samples=[
            Phase4Sample("pytorch hakkında araştırma yap", "research"),
            Phase4Sample("dosya oluştur", "file"),
            Phase4Sample("landing page üret", "website"),
        ],
        experiment_name="phase4_ab",
    )
    assert comparison["winner"] in {"v1.0.0", "v2.0.0"}
    assert Path(tmp_path / "phase4" / "ab_tests" / "phase4_ab.json").exists()


def test_training_config_scales_with_dataset_size(tmp_path: Path) -> None:
    pipeline = Phase4Pipeline(storage_root=tmp_path / "phase4")
    small = pipeline.suggest_training_config(12, base_model="local-proto")
    large = pipeline.suggest_training_config(256, base_model="local-proto")

    assert small.num_epochs >= large.num_epochs
    assert small.batch_size <= large.batch_size
    assert small.quantization_bits in {4, 8}
    assert large.target_f1 == pytest.approx(0.90)
