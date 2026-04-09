from types import SimpleNamespace

from core.agent import Agent


class _NoopMemory:
    def get_recent_conversations(self, user_id, limit=5):
        _ = (user_id, limit)
        return []

    def store_conversation(self, user_id, user_input, bot_response):
        _ = (user_id, user_input, bot_response)
        return None


class _FakeRuntimeSessionAPI:
    def __init__(self):
        self.recent_calls = []
        self.append_calls = []

    def get_recent_conversations(self, *, user_id, limit, runtime_metadata):
        self.recent_calls.append(
            {
                "user_id": user_id,
                "limit": limit,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return [{"user_message": "Onceki mesaj", "bot_response": "Onceki cevap", "workspace_id": "workspace-a"}]

    def append_turn(self, *, user_id, user_input, response_text, action, success, runtime_metadata):
        self.append_calls.append(
            {
                "user_id": user_id,
                "user_input": user_input,
                "response_text": response_text,
                "action": action,
                "success": success,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return {"conversation_session_id": "conv_test_001"}


def _make_agent() -> Agent:
    agent = Agent.__new__(Agent)
    agent.kernel = SimpleNamespace(memory=_NoopMemory())
    return agent


def test_safe_get_recent_conversations_prefers_runtime_session_api(monkeypatch):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("core.runtime.session_store.get_runtime_session_api", lambda: api)

    agent = _make_agent()
    rows = Agent._safe_get_recent_conversations(
        agent,
        "user-1",
        limit=4,
        metadata={"workspace_id": "workspace-a", "session_id": "sess-1", "channel": "desktop"},
    )

    assert rows[0]["user_message"] == "Onceki mesaj"
    assert api.recent_calls[0]["runtime_metadata"]["session_id"] == "sess-1"


def test_safe_store_conversation_writes_through_runtime_session_api(monkeypatch):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("core.runtime.session_store.get_runtime_session_api", lambda: api)

    agent = _make_agent()
    Agent._safe_store_conversation(
        agent,
        "user-1",
        "Merhaba",
        "Selam",
        "chat",
        True,
        metadata={"workspace_id": "workspace-a", "session_id": "sess-1", "channel": "desktop"},
    )

    assert api.append_calls
    assert api.append_calls[0]["user_input"] == "Merhaba"
    assert api.append_calls[0]["response_text"] == "Selam"
    assert api.append_calls[0]["runtime_metadata"]["workspace_id"] == "workspace-a"
