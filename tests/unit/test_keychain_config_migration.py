"""Unit tests for config channel token audit/migration helpers."""

import json
from pathlib import Path

from security.keychain import KeychainManager


def test_audit_config_plaintext_detects_channel_tokens(tmp_path: Path):
    cfg = tmp_path / "elyan.json"
    cfg.write_text(
        json.dumps(
            {
                "channels": [
                    {"type": "telegram", "token": "123:abc", "enabled": True},
                    {"type": "discord", "token": "$DISCORD_BOT_TOKEN", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = KeychainManager.audit_config_plaintext(cfg)
    assert result["exists"] is True
    assert len(result["findings"]) == 1
    assert result["findings"][0]["channel_type"] == "telegram"
    assert result["findings"][0]["env_key"] == "TELEGRAM_BOT_TOKEN"


def test_migrate_config_channel_tokens_no_keychain(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "elyan.json"
    cfg.write_text(
        json.dumps({"channels": [{"type": "telegram", "token": "123:abc", "enabled": True}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(KeychainManager, "is_available", staticmethod(lambda: False))
    result = KeychainManager.migrate_config_channel_tokens(cfg, clear_config=True)
    assert result["migrated"] == 0
    assert result["reason"] == "Keychain unavailable"
