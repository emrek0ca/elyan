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
        self.profile_calls = []
        self.draft_calls = []

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

    def get_preference_profile(self, *, user_id, runtime_metadata):
        self.profile_calls.append(
            {
                "user_id": user_id,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return {
            "explanation_style": "concise",
            "approval_sensitivity_hint": "strict",
            "preferred_model": "ollama/qwen2.5",
        }

    def list_learning_drafts(self, *, user_id, draft_type, limit, runtime_metadata):
        self.draft_calls.append(
            {
                "user_id": user_id,
                "draft_type": draft_type,
                "limit": limit,
                "runtime_metadata": dict(runtime_metadata or {}),
            }
        )
        return {
            "preferences": [
                {
                    "preference_key": "response_style",
                    "proposed_value": {"explanation_style": "concise"},
                    "rationale": "Kullanıcı kısa cevap istedi.",
                }
            ],
            "skills": [
                {
                    "name_hint": "daily_digest",
                    "description": "Her sabah günlük özet gönder.",
                    "status": "draft",
                }
            ],
            "routines": [
                {
                    "name_hint": "daily_summary",
                    "description": "Her sabah günlük özet gönder.",
                    "schedule_expression": "0 9 * * *",
                    "delivery_channel": "telegram",
                    "status": "draft",
                }
            ],
        }


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


def test_memory_run_profile_uses_runtime_session_api(monkeypatch, capsys):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("cli.commands.memory.get_runtime_database", lambda: _FakeRuntimeDB(), raising=False)
    monkeypatch.setattr("cli.commands.memory.get_runtime_session_api", lambda: api, raising=False)

    memory.run(SimpleNamespace(subcommand="profile", query=None, user=None))

    captured = capsys.readouterr()
    assert api.profile_calls[0]["user_id"] == "user-1"
    assert "Tercih Profili" in captured.out
    assert "concise" in captured.out


def test_memory_run_drafts_uses_runtime_session_api(monkeypatch, capsys):
    api = _FakeRuntimeSessionAPI()
    monkeypatch.setattr("cli.commands.memory.get_runtime_database", lambda: _FakeRuntimeDB(), raising=False)
    monkeypatch.setattr("cli.commands.memory.get_runtime_session_api", lambda: api, raising=False)

    memory.run(SimpleNamespace(subcommand="drafts", query=None, user=None, limit=4, draft_type="all"))

    captured = capsys.readouterr()
    assert api.draft_calls[0]["limit"] == 4
    assert "Preference Drafts" in captured.out
    assert "daily_digest" in captured.out
    assert "Routine Drafts" in captured.out
    assert "0 9 * * *" in captured.out
