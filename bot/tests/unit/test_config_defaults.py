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
