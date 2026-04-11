from types import SimpleNamespace

from cli.commands import memory


class _FakeAuthSessions:
    def get_latest_session(self, *, user_ref: str = "", workspace_id: str = ""):
        _ = (user_ref, workspace_id)
        return {
            "session_id": "session_1",
            "workspace_id": "workspace-a",
            "user_id": "user-1",
            "conversation_session_id": "conv_1",
            "metadata": {"client": "desktop"},
        }


class _FakeRuntimeDB:
    auth_sessions = _FakeAuthSessions()


class _FakeRuntimeSessionAPI:
    def __init__(self):
        self.recall_calls = []
        self.history_calls = []

    def ensure_auth_session(self, session):
        return dict(session)

    def search_history(self, *, user_id, query, limit, runtime_metadata):
        self.recall_calls.append(
            {
                "user_id": user_id,
                "query": query,
                "limit": limit,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return [
            {
                "channel": "telegram",
                "user_message": "Iyzico checkout hatasi neydi?",
                "bot_response": "Webhook imzasini compare_digest ile duzeltmistik.",
                "timestamp": 123.0,
            }
        ]

    def list_recent_history(self, *, user_id, limit, runtime_metadata):
        self.history_calls.append(
            {
                "user_id": user_id,
                "limit": limit,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return [
            {
                "channel": "desktop",
                "user_message": "Dunku toplantiyi ozetle",
                "bot_response": "Odeme akisini kapattik.",
                "timestamp": 456.0,
            }
        ]


def test_memory_run_recall_uses_runtime_session_api(monkeypatch, capsys):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("cli.commands.memory.get_runtime_database", lambda: _FakeRuntimeDB(), raising=False)
    monkeypatch.setattr("cli.commands.memory.get_runtime_session_api", lambda: api, raising=False)

    memory.run(SimpleNamespace(subcommand="recall", query="iyzico", user=None, limit=5))

    captured = capsys.readouterr()
    assert api.recall_calls[0]["query"] == "iyzico"
    assert "Iyzico checkout hatasi neydi?" in captured.out
    assert "compare_digest" in captured.out


def test_memory_run_history_uses_runtime_session_api(monkeypatch, capsys):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("cli.commands.memory.get_runtime_database", lambda: _FakeRuntimeDB(), raising=False)
    monkeypatch.setattr("cli.commands.memory.get_runtime_session_api", lambda: api, raising=False)

    memory.run(SimpleNamespace(subcommand="history", query=None, user=None, limit=2))

    captured = capsys.readouterr()
    assert api.history_calls[0]["limit"] == 2
    assert "Dunku toplantiyi ozetle" in captured.out
