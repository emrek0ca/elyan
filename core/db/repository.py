from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.storage_paths import resolve_runtime_db_path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


CORE_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="consent_policies",
        sql="""
        CREATE TABLE IF NOT EXISTS consent_policies (
            consent_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            granted INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'privacy_engine',
            expires_at REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_consent_policies_user_workspace
            ON consent_policies(user_id, workspace_id, updated_at DESC);
        """,
    ),
    Migration(
        version=2,
        name="artifact_manifests",
        sql="""
        CREATE TABLE IF NOT EXISTS artifact_manifests (
            artifact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            file_path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            manifest_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_artifact_manifests_project_phase
            ON artifact_manifests(project_id, phase, updated_at DESC);
        """,
    ),
)


class DbManager:
    def __init__(self, db_path: str | Path | None = None, *, migrations: Sequence[Migration] | None = None) -> None:
        self.db_path = Path(db_path or resolve_runtime_db_path()).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrations = tuple(sorted(migrations or CORE_MIGRATIONS, key=lambda item: int(item.version)))
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in conn.execute("SELECT version FROM schema_version").fetchall()
            }
            for migration in self.migrations:
                if migration.version in applied:
                    continue
                conn.executescript(migration.sql)
                conn.execute(
                    "INSERT INTO schema_version(version, name, applied_at) VALUES(?, ?, ?)",
                    (int(migration.version), str(migration.name), time.time()),
                )
            conn.commit()

    def integrity_check(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0] if row else "unknown").strip().lower()
        return {"ok": result == "ok", "result": result}

    def backup(self, destination: str | Path) -> Path:
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, target)
        return target


class Repository:
    def __init__(self, manager: DbManager | None = None) -> None:
        self.manager = manager or get_db_manager()

    def fetchone(self, query: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        with self.manager.connect() as conn:
            row = conn.execute(query, tuple(params or ())).fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        with self.manager.connect() as conn:
            rows = conn.execute(query, tuple(params or ())).fetchall()
        return [dict(row) for row in rows]

    def execute(self, query: str, params: Sequence[Any] | None = None) -> int:
        with self.manager.connect() as conn:
            cursor = conn.execute(query, tuple(params or ()))
            conn.commit()
        return int(cursor.rowcount or 0)

    def executemany(self, query: str, seq_of_params: Iterable[Sequence[Any]]) -> int:
        with self.manager.connect() as conn:
            cursor = conn.executemany(query, list(seq_of_params))
            conn.commit()
        return int(cursor.rowcount or 0)


_db_manager: DbManager | None = None


def get_db_manager(db_path: str | Path | None = None) -> DbManager:
    global _db_manager
    if db_path is not None:
        return DbManager(db_path=db_path)
    if _db_manager is None:
        _db_manager = DbManager()
    return _db_manager


__all__ = ["CORE_MIGRATIONS", "DbManager", "Migration", "Repository", "get_db_manager"]
