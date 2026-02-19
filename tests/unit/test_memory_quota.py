"""Unit tests for per-user memory quota enforcement."""

from pathlib import Path

from core.memory import Memory, MemoryManager


def test_quota_prunes_oldest_conversation(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELYAN_MAX_USER_MEMORY_BYTES", "900")
    memory = Memory(db_path=str(tmp_path / "memory.db"))

    payload = {
        "action": "chat",
        "success": True,
        "message": "x" * 320,
    }
    first_id = memory.store_conversation(user_id=42, user_message="a" * 320, bot_response=payload)
    second_id = memory.store_conversation(user_id=42, user_message="b" * 320, bot_response=payload)

    assert first_id > 0
    assert second_id > 0

    rows = memory.get_recent_conversations(user_id=42, limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == second_id

    usage = memory.get_user_storage_stats(user_id=42)
    assert usage["used_bytes"] <= usage["limit_bytes"]


def test_quota_rejects_single_item_larger_than_cap(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELYAN_MAX_USER_MEMORY_BYTES", "200")
    memory = Memory(db_path=str(tmp_path / "memory.db"))

    too_large = memory.store_conversation(
        user_id=7,
        user_message="z" * 500,
        bot_response={"action": "chat", "success": True, "message": "z" * 500},
    )
    assert too_large == -1
    assert memory.get_recent_conversations(user_id=7, limit=10) == []


def test_memory_manager_exposes_user_storage_stats(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELYAN_MAX_USER_MEMORY_BYTES", "1024")
    db_path = str(tmp_path / "memory.db")
    memory = Memory(db_path=db_path)
    memory.store_conversation(
        user_id=99,
        user_message="hello",
        bot_response={"action": "chat", "success": True, "message": "world"},
    )

    manager = MemoryManager(db_path=db_path)
    stats = manager.get_stats(user_id=99)

    assert "user_storage" in stats
    assert stats["user_storage"]["user_id"] == 99
    assert stats["user_storage"]["limit_bytes"] == 1024


def test_top_users_storage_returns_sorted_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELYAN_MAX_USER_MEMORY_BYTES", "4096")
    memory = Memory(db_path=str(tmp_path / "memory.db"))

    memory.store_conversation(1, "a" * 200, {"action": "chat", "success": True, "message": "x" * 200})
    memory.store_conversation(2, "b" * 500, {"action": "chat", "success": True, "message": "y" * 500})

    top = memory.get_top_users_storage(limit=2)
    assert len(top) == 2
    assert top[0]["user_id"] == 2
    assert top[0]["used_bytes"] >= top[1]["used_bytes"]


def test_config_file_sets_default_user_limit_when_env_missing(monkeypatch, tmp_path: Path):
    fake_home = tmp_path / "home"
    config_dir = fake_home / ".elyan"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "elyan.json").write_text(
        '{"memory": {"maxUserStorageGB": 1.5}}',
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELYAN_MAX_USER_MEMORY_BYTES", raising=False)
    monkeypatch.delenv("ELYAN_MAX_USER_MEMORY_GB", raising=False)

    memory = Memory()
    assert round(memory.default_user_limit_bytes / (1024 ** 3), 2) == 1.5
