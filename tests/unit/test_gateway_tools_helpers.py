import pytest

from core.gateway import server


def test_get_policy_lists_reads_camel_case_require_approval(monkeypatch):
    values = {
        "tools.allow": ["group:fs"],
        "tools.deny": ["delete_file"],
        "tools.requireApproval": ["write_file"],
        "tools.require_approval": None,
    }
    monkeypatch.setattr(server.elyan_config, "get", lambda key, default=None: values.get(key, default))
    allow, deny, require = server._get_policy_lists()
    assert allow == ["group:fs"]
    assert deny == ["delete_file"]
    assert require == ["write_file"]


def test_unique_clean_dedupes_and_strips():
    assert server._unique_clean([" a ", "a", "", None, "b"], []) == ["a", "b"]


def test_default_model_for_provider_mapping():
    assert server._default_model_for_provider("openai") == "gpt-4o"
    assert server._default_model_for_provider("anthropic") == "claude-3-5-sonnet-latest"
    assert server._default_model_for_provider("google") == "gemini-2.0-flash"
    assert server._default_model_for_provider("groq") == "llama-3.3-70b-versatile"
    assert server._default_model_for_provider("ollama") == "llama3.1:8b"


def test_provider_key_status_prefers_keychain(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(server.elyan_config, "get", lambda key, default=None: "" if key == "models.providers.openai.apiKey" else default)
    monkeypatch.setattr(server.KeychainManager, "key_for_env", staticmethod(lambda env: "openai_api_key" if env == "OPENAI_API_KEY" else None))
    monkeypatch.setattr(server.KeychainManager, "get_key", staticmethod(lambda key: "sk-test" if key == "openai_api_key" else ""))

    status = server._provider_key_status("openai")
    assert status["configured"] is True
    assert status["source"] == "keychain"


def test_sanitize_roles_map_filters_invalid_entries():
    out = server._sanitize_roles_map(
        {
            "reasoning": {"provider": "openai", "model": "gpt-4o"},
            "invalid": {"provider": "x", "model": "y"},
            "code": {"provider": "groq", "model": ""},
        },
        default_provider="openai",
        default_model="gpt-4o",
    )
    assert "reasoning" in out
    assert "invalid" not in out
    assert out["code"]["provider"] == "groq"
    assert out["code"]["model"] == server._default_model_for_provider("groq")


def test_looks_like_automation_request_requires_schedule_and_action():
    cls = server.ElyanGatewayServer
    assert cls._looks_like_automation_request("Her gün saat 09:00 paneli kontrol et ve rapor gönder") is True
    assert cls._looks_like_automation_request("paneli kontrol et") is False
    assert cls._looks_like_automation_request("her gün saat 09:00 merhaba") is False


def test_task_intent_snapshot_detects_reminder_automation():
    cls = server.ElyanGatewayServer
    snap = cls._task_intent_snapshot("Her gün saat 22:00 ilaç içmem için hatırlat ve telegramdan gönder")
    assert snap["has_schedule"] is True
    assert snap["has_action"] is True
    assert snap["should_auto_create"] is True


def test_task_intent_snapshot_ignores_general_question():
    cls = server.ElyanGatewayServer
    snap = cls._task_intent_snapshot("Fatih Sultan Mehmet kimdir?")
    assert snap["has_schedule"] is False
    assert snap["should_auto_create"] is False


def test_channel_secret_env_mapping():
    assert server._channel_secret_env("token", "telegram") == "TELEGRAM_BOT_TOKEN"
    assert server._channel_secret_env("bridge_token", "whatsapp") == "WHATSAPP_BRIDGE_TOKEN"
    assert server._channel_secret_env("access_token", "whatsapp") == "WHATSAPP_ACCESS_TOKEN"
    assert server._channel_secret_env("verify_token", "whatsapp") == "WHATSAPP_VERIFY_TOKEN"
    assert server._channel_secret_env("app_token", "slack") == "SLACK_APP_TOKEN"
    assert server._channel_secret_env("unknown", "telegram") == ""


def test_channel_id_prefers_id_then_type():
    assert server._channel_id({"id": "tg-main", "type": "telegram"}) == "tg-main"
    assert server._channel_id({"type": "telegram"}) == "telegram"
    assert server._channel_id({}) == ""


def test_normalize_channel_type_converts_hyphen():
    assert server._normalize_channel_type("google-chat") == "google_chat"


@pytest.mark.asyncio
async def test_fetch_memory_stats_uses_nested_memory_fallback():
    class _Inner:
        def get_stats(self):
            return {"conversations": 7, "database_size_bytes": 123}

    class _Outer:
        memory = _Inner()

    stats = await server._fetch_memory_stats(_Outer())
    assert stats["conversations"] == 7
    assert stats["database_size_bytes"] == 123


@pytest.mark.asyncio
async def test_fetch_memory_top_users_uses_first_available():
    class _Inner:
        def get_top_users_storage(self, limit=5):
            return [{"user_id": 1, "used_bytes": 42}][:limit]

    class _Outer:
        memory = _Inner()

    rows = await server._fetch_memory_top_users(_Outer(), limit=3)
    assert rows and rows[0]["user_id"] == 1
