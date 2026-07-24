"""P0 — SQLite tabanlı dayanıklı status/artifact outbox'ı + terminal fence.

Görev sonuç/artifact raporları backend'e ulaşana kadar burada yaşar:

- delivery ACK: teslimat ancak alıcı onayıyla (ok) 'delivered' olur.
- bounded retry: attempts >= MAX_ATTEMPTS → 'dead' (sonsuz döngü yok).
- exponential backoff + deterministik jitter: next_attempt_at sütunu.
- daemon restart sonrası teslim: kayıtlar diskte; drain() yeni süreçte de
  bekleyenleri gönderir.

Ayrıca süreçler arası ATOMİK terminal claim (claim_terminal) ve monoton,
reconnect sonrası replay edilebilir progress sequence (next_progress_sequence /
record_progress_event / replay_progress_events) aynı DB'de tutulur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable

from runtime import state_store

MAX_DELIVERY_ATTEMPTS = 12
_BACKOFF_BASE_SECONDS = 1.5
_BACKOFF_CAP_SECONDS = 300.0
_PROGRESS_EVENT_LIMIT_PER_TASK = 200


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso(value: dt.datetime | None = None) -> str:
    return (value or _utc_now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_path() -> Path:
    return Path(state_store.STATE_PATH).parent / "durable_outbox.sqlite3"


def backoff_seconds(attempts: int, *, seed: str = "") -> float:
    """Bounded exponential backoff + deterministik jitter (test edilebilir)."""
    base = min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)))
    digest = hashlib.sha256(f"{seed}:{attempts}".encode("utf-8")).digest()
    jitter = random.Random(digest).uniform(0.0, base * 0.25)
    return base + jitter


class DurableOutbox:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    entry_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    delivered_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_due
                    ON outbox(status, next_attempt_at);
                CREATE TABLE IF NOT EXISTS terminal_claims (
                    task_id TEXT PRIMARY KEY,
                    claimed_at TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS progress_sequences (
                    task_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS progress_events (
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, sequence)
                );
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ outbox

    def enqueue(self, task_id: str, kind: str, payload: dict[str, Any], *, entry_id: str = "") -> str:
        """Teslim edilecek raporu kalıcı kuyruğa yazar; entry_id ile idempotent."""
        normalized_id = str(entry_id or "").strip() or f"out_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO outbox (entry_id, task_id, kind, payload, status, attempts, next_attempt_at, created_at)
                VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    payload = excluded.payload,
                    status = CASE WHEN outbox.status = 'delivered' THEN outbox.status ELSE 'pending' END
                """,
                (
                    normalized_id,
                    str(task_id or "").strip(),
                    str(kind or "status")[:32],
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _utc_iso(),
                    _utc_iso(),
                ),
            )
        return normalized_id

    def due_entries(self, *, now: dt.datetime | None = None, limit: int = 16) -> list[dict[str, Any]]:
        cutoff = _utc_iso(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY created_at ASC LIMIT ?
                """,
                (cutoff, max(1, int(limit))),
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except ValueError:
                payload = {}
            entries.append(
                {
                    "entryId": row["entry_id"],
                    "taskId": row["task_id"],
                    "kind": row["kind"],
                    "payload": payload if isinstance(payload, dict) else {},
                    "attempts": int(row["attempts"] or 0),
                }
            )
        return entries

    def mark_delivered(self, entry_id: str) -> None:
        """Delivery ACK — yalnız alıcı onayladığında çağrılır."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE outbox SET status='delivered', delivered_at=? WHERE entry_id=?",
                (_utc_iso(), str(entry_id or "")),
            )

    def mark_attempt_failed(self, entry_id: str, *, error: str = "") -> None:
        """Başarısız deneme: bounded retry + exponential backoff + jitter."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM outbox WHERE entry_id=?",
                (str(entry_id or ""),),
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"] or 0) + 1
            if attempts >= MAX_DELIVERY_ATTEMPTS:
                connection.execute(
                    "UPDATE outbox SET status='dead', attempts=?, last_error=? WHERE entry_id=?",
                    (attempts, str(error or "")[:240], str(entry_id or "")),
                )
                return
            delay = backoff_seconds(attempts, seed=str(entry_id))
            next_attempt = _utc_iso(_utc_now() + dt.timedelta(seconds=delay))
            connection.execute(
                "UPDATE outbox SET attempts=?, next_attempt_at=?, last_error=? WHERE entry_id=?",
                (attempts, next_attempt, str(error or "")[:240], str(entry_id or "")),
            )

    def drain(
        self,
        deliver: Callable[[dict[str, Any]], bool],
        *,
        limit: int = 16,
        now: dt.datetime | None = None,
    ) -> dict[str, int]:
        """Vadesi gelen kayıtları teslim etmeyi dener. `deliver(entry) -> bool`
        True dönerse ACK sayılır. Restart sonrası da aynı yol çalışır."""
        delivered = 0
        failed = 0
        for entry in self.due_entries(now=now, limit=limit):
            ok = False
            error = ""
            try:
                ok = bool(deliver(entry))
            except Exception as exc:
                error = type(exc).__name__
            if ok:
                self.mark_delivered(entry["entryId"])
                delivered += 1
            else:
                self.mark_attempt_failed(entry["entryId"], error=error or "delivery_rejected")
                failed += 1
        return {"delivered": delivered, "failed": failed}

    def pending_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM outbox WHERE status='pending'"
            ).fetchone()
        return int(row["c"] or 0)

    def entry_status(self, entry_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM outbox WHERE entry_id=?",
                (str(entry_id or ""),),
            ).fetchone()
        return str(row["status"]) if row is not None else ""

    # ------------------------------------------------------------------ terminal fence

    def claim_terminal(self, task_id: str) -> bool:
        """Süreçler arası TEK atomik terminal claim: ilk claim True, sonrakiler
        False. Geç kalan worker'lar terminal/progress yazamaz."""
        normalized = str(task_id or "").strip()
        if not normalized:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO terminal_claims(task_id, claimed_at) VALUES(?, ?)",
                (normalized, _utc_iso()),
            )
            return cursor.rowcount > 0

    def is_terminal_claimed(self, task_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM terminal_claims WHERE task_id=?",
                (str(task_id or "").strip(),),
            ).fetchone()
        return row is not None

    def release_terminal(self, task_id: str) -> None:
        """Yalnız test/bakım amaçlı; normal akışta terminal claim kalıcıdır."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM terminal_claims WHERE task_id=?",
                (str(task_id or "").strip(),),
            )

    # ------------------------------------------------------------------ progress

    def next_progress_sequence(self, task_id: str) -> int:
        """Görev başına monoton artan sequence (süreçler/restart'lar arası)."""
        normalized = str(task_id or "").strip() or "unknown"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT sequence FROM progress_sequences WHERE task_id=?",
                    (normalized,),
                ).fetchone()
                sequence = int(row["sequence"] or 0) + 1 if row is not None else 1
                connection.execute(
                    """
                    INSERT INTO progress_sequences(task_id, sequence) VALUES(?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET sequence=excluded.sequence
                    """,
                    (normalized, sequence),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return sequence

    def record_progress_event(self, task_id: str, sequence: int, payload: dict[str, Any]) -> str:
        """Reconnect sonrası replay için olayı kalıcı halkaya yazar."""
        normalized = str(task_id or "").strip() or "unknown"
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO progress_events(task_id, sequence, event_id, payload, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    int(sequence),
                    event_id,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    _utc_iso(),
                ),
            )
            connection.execute(
                """
                DELETE FROM progress_events
                WHERE task_id = ? AND sequence <= (
                    SELECT MAX(sequence) FROM progress_events WHERE task_id = ?
                ) - ?
                """,
                (normalized, normalized, _PROGRESS_EVENT_LIMIT_PER_TASK),
            )
        return event_id

    def replay_progress_events(self, task_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_id, payload FROM progress_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (str(task_id or "").strip() or "unknown", int(after_sequence)),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except ValueError:
                payload = {}
            if isinstance(payload, dict):
                payload = dict(payload)
                payload.setdefault("sequence", int(row["sequence"]))
                payload.setdefault("eventId", str(row["event_id"]))
                events.append(payload)
        return events
