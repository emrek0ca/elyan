import sqlite3
import pathlib
import time
import os
from typing import List, Dict, Any, Optional
from utils.logger import get_logger
from core.observability.logger import get_structured_logger

logger = get_logger("file_indexer")
slog = get_structured_logger("file_indexer")

class FileIndexer:
    """
    Maintains a local SQLite index of the filesystem for fast searching.
    """
    def __init__(self, db_path: Optional[pathlib.Path] = None):
        self.db_path = db_path or pathlib.Path.home() / ".elyan" / "file_index.db"
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    filename TEXT,
                    extension TEXT,
                    size INTEGER,
                    modified_at REAL,
                    indexed_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_filename ON files(filename)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extension ON files(extension)")

    def index_path(self, root_path: str):
        """Crawls and indexes a directory."""
        root = pathlib.Path(root_path).expanduser().resolve()
        slog.log_event("indexing_started", {"root": str(root)})
        
        count = 0
        with sqlite3.connect(str(self.db_path)) as conn:
            for p in root.rglob("*"):
                if p.is_file():
                    try:
                        stat = p.stat()
                        conn.execute("""
                            INSERT OR REPLACE INTO files (path, filename, extension, size, modified_at, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            str(p),
                            p.name,
                            p.suffix.lower(),
                            stat.st_size,
                            stat.st_mtime,
                            time.time()
                        ))
                        count += 1
                        if count % 100 == 0:
                            conn.commit()
                    except Exception:
                        continue
            conn.commit()
            
        slog.log_event("indexing_finished", {"root": str(root), "files_indexed": count})

    def search(self, query: str, extension: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Searches the index for files matching the query."""
        sql = "SELECT path, filename, size, modified_at FROM files WHERE filename LIKE ?"
        params = [f"%{query}%"]
        
        if extension:
            sql += " AND extension = ?"
            params.append(extension.lower() if extension.startswith(".") else f".{extension.lower()}")
            
        sql += " ORDER BY modified_at DESC LIMIT ?"
        params.append(limit)
        
        results = []
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            for row in rows:
                results.append(dict(row))
                
        return results

# Global instance
file_indexer = FileIndexer()
