"""Unit tests for roadmap-aligned config defaults."""

from config.elyan_config import _default_config
from core.domain.models import AppConfig


def test_app_config_preserves_extra_fields():
    cfg = AppConfig(custom={"team": "elyan"})
    dumped = cfg.model_dump()
    assert dumped["custom"]["team"] == "elyan"


def test_default_config_enforces_local_memory_baseline():
    cfg = _default_config()
    assert cfg.memory.get("enabled") is True
    assert cfg.memory.get("localOnly") is True
    assert cfg.memory.get("maxUserStorageGB") == 10
    assert cfg.gateway.get("port") == 18789
    assert cfg.personalization.get("enabled") is True
    assert cfg.personalization.get("mode") == "hybrid"
    assert cfg.personalization.get("vector_backend") == "lancedb"
    assert cfg.personalization.get("graph_backend") == "sqlite"
    assert cfg.ml.get("enabled") is True
    assert cfg.ml.get("execution_mode") == "local_first"
    assert cfg.evaluation.get("verifier_threshold") == 0.55
    assert cfg.retrieval.get("top_k") == 5
    assert cfg.runtime_control.get("enabled") is True
