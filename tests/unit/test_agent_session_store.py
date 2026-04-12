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
        self.ensure_calls = []
        self.preference_drafts = []
        self.skill_drafts = []
        self.routine_drafts = []
        self.db = SimpleNamespace(
            learning=SimpleNamespace(
                enqueue_preference_update=self._enqueue_preference_update,
                enqueue_skill_draft=self._enqueue_skill_draft,
                enqueue_routine_draft=self._enqueue_routine_draft,
            )
        )

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

    def ensure_session(self, *, user_id, runtime_metadata, metadata=None):
        self.ensure_calls.append(
            {
                "user_id": user_id,
                "runtime_metadata": dict(runtime_metadata or {}),
                "metadata": dict(metadata or {}),
            }
        )
        return {
            "conversation_session_id": str((runtime_metadata or {}).get("conversation_session_id") or "conv_test_001"),
            "workspace_id": str((runtime_metadata or {}).get("workspace_id") or "workspace-a"),
            "actor_id": str((runtime_metadata or {}).get("user_id") or user_id),
        }

    def _enqueue_preference_update(self, **payload):
        self.preference_drafts.append(dict(payload))
        return {"queue_id": "prefdraft_1"}

    def _enqueue_skill_draft(self, **payload):
        self.skill_drafts.append(dict(payload))
        return {"draft_id": "skilldraft_1"}

    def _enqueue_routine_draft(self, **payload):
        self.routine_drafts.append(dict(payload))
        return {"draft_id": "routinedraft_1"}


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


def test_queue_learning_drafts_writes_preference_skill_and_routine_drafts(monkeypatch):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("core.runtime.session_store.get_runtime_session_api", lambda: api)

    agent = _make_agent()
    queued = Agent._queue_learning_drafts(
        agent,
        "user-1",
        user_input="Lütfen kısa cevap ver ve bunu skill yap, her sabah bana özet gönder.",
        response_text="Tamam, bunu tercih ve rutin taslağı olarak not aldım.",
        action="send_message",
        success=True,
        context={"tool_results": [{"tool": "send_message"}], "channel": "desktop"},
        runtime_metadata={
            "workspace_id": "workspace-a",
            "user_id": "user-1",
            "conversation_session_id": "conv-1",
            "channel": "desktop",
            "agent_mode": "automation",
        },
    )

    assert queued == {"preferences": 1, "skills": 1, "routines": 1}
    assert api.preference_drafts[0]["preference_key"] == "response_style"
    assert api.preference_drafts[0]["metadata"]["agent_mode"] == "automation"
    assert api.skill_drafts[0]["source_action"] == "send_message"
    assert api.skill_drafts[0]["conversation_session_id"] == "conv-1"
    assert api.routine_drafts[0]["schedule_expression"] == "0 9 * * *"
