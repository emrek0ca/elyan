"""Unit tests for memory embedding storage consistency."""

from pathlib import Path

from core.memory import Memory


def test_store_and_load_embedding_with_canonical_format(tmp_path: Path):
    db_path = str(tmp_path / "memory.db")
    memory = Memory(db_path=db_path)

    emb_id = memory.store_embedding(
        user_id=7,
        embedding='[1,2,3]',
        model="test-model",
        metadata={"source": "unit"},
    )
    assert emb_id > 0

    rows = memory.get_user_embeddings(user_id=7, limit=10)
    assert len(rows) == 1
    assert rows[0]["embedding"] == [1.0, 2.0, 3.0]
    assert rows[0]["model"] == "test-model"
    assert rows[0]["metadata"]["source"] == "unit"


def test_store_conversation_persists_embedding_if_present(tmp_path: Path):
    db_path = str(tmp_path / "memory.db")
    memory = Memory(db_path=db_path)

    conv_id = memory.store_conversation(
        user_id=11,
        user_message="hello",
        bot_response={
            "action": "chat",
            "success": True,
            "message": "ok",
            "embedding": [0.1, 0.2],
            "embedding_model": "mini",
            "embedding_metadata": {"kind": "conversation"},
        },
    )
    assert conv_id > 0

    rows = memory.get_user_embeddings(user_id=11, limit=10)
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == conv_id
    assert rows[0]["embedding"] == [0.1, 0.2]
