"""Unit tests for audit logger behavior."""

from pathlib import Path

from security.audit import AuditLogger


def test_operation_history_filters_and_decodes_json(tmp_path: Path):
    db_path = str(tmp_path / "audit.db")
    logger = AuditLogger(db_path=db_path)

    logger.log_operation(
        user_id=42,
        operation="read_file",
        params={"path": "/tmp/a.txt"},
        result={"ok": True},
        success=True,
    )
    logger.log_operation(
        user_id=99,
        operation="write_file",
        params={"path": "/tmp/b.txt"},
        result={"ok": False},
        success=False,
    )

    rows = logger.get_operation_history(user_id=42, operation="read_file", limit=10)
    assert len(rows) == 1
    assert rows[0]["user_id"] == 42
    assert rows[0]["operation"] == "read_file"
    assert rows[0]["params"]["path"] == "/tmp/a.txt"
    assert rows[0]["result"]["ok"] is True


def test_security_events_filter_and_decode_details(tmp_path: Path):
    db_path = str(tmp_path / "audit.db")
    logger = AuditLogger(db_path=db_path)

    logger.log_security_event(
        event_type="rate_limit",
        severity="high",
        description="too many requests",
        user_id=7,
        details={"count": 30},
        source="telegram",
    )
    logger.log_security_event(
        event_type="auth",
        severity="low",
        description="auth ok",
        user_id=7,
        details={"count": 1},
        source="telegram",
    )

    rows = logger.get_security_events(severity="high", limit=10)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "rate_limit"
    assert rows[0]["details"]["count"] == 30
