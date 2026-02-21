"""Unit tests for keychain plaintext audit/migration helpers."""

from pathlib import Path

from security.keychain import KeychainManager


def test_audit_env_plaintext_detects_sensitive_entries(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=sk-test\n"
        "TELEGRAM_BOT_TOKEN=123:abc\n"
        "GOOGLE_API_KEY=$GOOGLE_API_KEY\n"
        "NORMAL_KEY=value\n",
        encoding="utf-8",
    )

    result = KeychainManager.audit_env_plaintext(env_file)
    keys = {x["env_key"] for x in result["findings"]}
    assert "OPENAI_API_KEY" in keys
    assert "TELEGRAM_BOT_TOKEN" in keys
    # Variable reference should not be treated as plaintext secret
    assert "GOOGLE_API_KEY" not in keys


def test_migrate_from_env_no_keychain_returns_reason(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")

    monkeypatch.setattr(KeychainManager, "is_available", staticmethod(lambda: False))
    result = KeychainManager.migrate_from_env(env_file, clear_env=True)
    assert result["migrated"] == 0
    assert result["reason"] == "Keychain unavailable"


def test_key_for_env_supports_slack_app_token():
    assert KeychainManager.key_for_env("SLACK_APP_TOKEN") == "slack_app_token"


def test_key_for_env_supports_whatsapp_cloud_tokens():
    assert KeychainManager.key_for_env("WHATSAPP_ACCESS_TOKEN") == "whatsapp_access_token"
    assert KeychainManager.key_for_env("WHATSAPP_VERIFY_TOKEN") == "whatsapp_verify_token"
