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
