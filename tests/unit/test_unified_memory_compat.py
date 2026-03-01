import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

from core.memory.unified import UnifiedMemory


def _prepare_conversation_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
        """
    )
    cur.execute("INSERT INTO conversations (user_id, role, content) VALUES (1, 'user', 'kısa')")
    cur.execute("INSERT INTO conversations (user_id, role, content) VALUES (2, 'user', 'çok daha uzun içerik')")
    cur.execute("INSERT INTO conversations (user_id, role, content) VALUES (2, 'assistant', 'orta')")
    conn.commit()
    conn.close()


def _prepare_episodic_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 1,
            metadata TEXT
        )
        """
    )
    cur.execute("INSERT INTO events (user_id, timestamp, event_type, content) VALUES ('1', 1.0, 'evt', 'a')")
    cur.execute("INSERT INTO events (user_id, timestamp, event_type, content) VALUES ('2', 2.0, 'evt', 'b')")
    conn.commit()
    conn.close()


def test_unified_memory_uses_legacy_stats_when_available(monkeypatch):
    legacy_obj = SimpleNamespace(
        get_stats=lambda: {"conversations": 9, "preferences": 1, "tasks": 2, "knowledge_items": 3, "embeddings": 4},
        get_top_users_storage=lambda limit=5: [{"user_id": 42, "used_bytes": 1234}],
    )
    monkeypatch.setitem(
        sys.modules,
        "core._memory_legacy",
        SimpleNamespace(_memory_instance=legacy_obj, get_memory=lambda: legacy_obj),
    )

    memory = UnifiedMemory()
    stats = memory.get_stats()
    top = memory.get_top_users_storage(limit=5)

    assert stats["conversations"] == 9
    assert stats["embeddings"] == 4
    assert top == [{"user_id": 42, "used_bytes": 1234}]


def test_unified_memory_fallback_stats_and_top_users(monkeypatch, tmp_path: Path):
    monkeypatch.delitem(sys.modules, "core._memory_legacy", raising=False)
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))

    conv_db = fake_home / ".config" / "cdacs-bot" / "conversation.db"
    episodic_db = fake_home / ".elyan" / "memory" / "episodic.db"
    patterns = fake_home / ".elyan" / "memory" / "patterns.md"
    patterns.parent.mkdir(parents=True, exist_ok=True)
    patterns.write_text("### Entry: 1\nx\n### Entry: 2\ny\n", encoding="utf-8")

    _prepare_conversation_db(conv_db)
    _prepare_episodic_db(episodic_db)

    memory = UnifiedMemory()
    stats = memory.get_stats()
    top = memory.get_top_users_storage(limit=2)

    assert stats["conversations"] == 3
    assert stats["users"] == 2
    assert stats["tasks"] == 2
    assert stats["knowledge_items"] == 2
    assert isinstance(top, list)
    assert len(top) == 2
    assert top[0]["used_bytes"] >= top[1]["used_bytes"]
