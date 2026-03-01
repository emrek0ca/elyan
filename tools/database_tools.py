"""
Elyan Database Tools — SQLite, PostgreSQL, MySQL connectivity

CRUD, schema inspection, migration, backup/restore.
"""

import asyncio
import json
import os
import sqlite3
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("database_tools")

DB_WORKSPACE = Path.home() / ".elyan" / "databases"
DB_WORKSPACE.mkdir(parents=True, exist_ok=True)


async def db_connect(db_path: str = None, db_type: str = "sqlite") -> Dict[str, Any]:
    """Connect to a database and return connection info."""
    if db_type == "sqlite":
        path = db_path or str(DB_WORKSPACE / "default.db")
        try:
            conn = sqlite3.connect(path)
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            conn.close()
            return {"success": True, "type": "sqlite", "path": path, "tables": [t[0] for t in tables]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": f"Unsupported DB type: {db_type}"}


async def db_execute(query: str, db_path: str = None, params: list = None) -> Dict[str, Any]:
    """Execute a SQL query on a SQLite database."""
    path = db_path or str(DB_WORKSPACE / "default.db")
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params or [])

        if query.strip().upper().startswith("SELECT"):
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return {"success": True, "rows": rows, "count": len(rows)}
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {"success": True, "affected_rows": affected}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def db_schema(db_path: str = None) -> Dict[str, Any]:
    """Get full schema of a SQLite database."""
    path = db_path or str(DB_WORKSPACE / "default.db")
    try:
        conn = sqlite3.connect(path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        schema = {}
        for (table_name,) in tables:
            cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            schema[table_name] = [{"name": c[1], "type": c[2], "notnull": bool(c[3]), "pk": bool(c[5])} for c in cols]
        conn.close()
        return {"success": True, "schema": schema, "table_count": len(schema)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def db_backup(db_path: str = None, backup_dir: str = None) -> Dict[str, Any]:
    """Backup a SQLite database."""
    path = db_path or str(DB_WORKSPACE / "default.db")
    dest_dir = backup_dir or str(DB_WORKSPACE / "backups")
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    import time
    backup_name = f"backup_{int(time.time())}.db"
    dest = os.path.join(dest_dir, backup_name)
    try:
        shutil.copy2(path, dest)
        return {"success": True, "backup_path": dest}
    except Exception as e:
        return {"success": False, "error": str(e)}
