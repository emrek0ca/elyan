"""Unit tests for secret reference resolution in elyan config."""

import os
from pathlib import Path

from config import settings
from config.elyan_config import ConfigurationManager


def test_get_resolves_env_secret_reference(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "ELYAN_DIR", tmp_path)
    cfg_path = tmp_path / "elyan.json"
    cfg_path.write_text(
        '{"channels":[{"type":"telegram","enabled":true,"token":"$TELEGRAM_BOT_TOKEN"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")

    cfg = ConfigurationManager()
    channels = cfg.get("channels", [])
    assert channels[0]["token"] == "123:abc"


def test_get_resolves_keychain_when_env_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "ELYAN_DIR", tmp_path)
    cfg_path = tmp_path / "elyan.json"
    cfg_path.write_text(
        '{"channels":[{"type":"telegram","enabled":true,"token":"$TELEGRAM_BOT_TOKEN"}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    from security.keychain import KeychainManager
    monkeypatch.setattr(KeychainManager, "get_key", staticmethod(lambda _k: "999:kc"))

    cfg = ConfigurationManager()
    channels = cfg.get("channels", [])
    assert channels[0]["token"] == "999:kc"
