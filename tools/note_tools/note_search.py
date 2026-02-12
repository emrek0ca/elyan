"""
Not Arama - Note Search
FTS5 ile tam metin arama desteği
"""

import sqlite3
from pathlib import Path
from typing import Any
from utils.logger import get_logger

logger = get_logger("note_search")

# Notes storage location
NOTES_DIR = Path.home() / "Documents" / "BotNotes"
DB_PATH = NOTES_DIR / ".notes_index.db"


def _get_db_connection() -> sqlite3.Connection:
    """SQLite veritabanı bağlantısı al"""
    if not DB_PATH.exists():
        # Return empty result if no database
        raise FileNotFoundError("Not veritabanı bulunamadı. Önce not oluşturun.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


async def search_notes(
    query: str,
    search_in: str = "all",
    category: str | None = None,
    tags: list[str] | str | None = None,
    limit: int = 20
) -> dict[str, Any]:
    """
    Notlarda tam metin arama yap

    Args:
        query: Arama sorgusu
        search_in: Arama alanı ("all", "title", "content", "tags")
        category: Kategori filtresi
        tags: Etiket filtresi
        limit: Maksimum sonuç sayısı

    Returns:
        dict: Arama sonuçları
    """
    try:
        if not query or not query.strip():
            return {"success": False, "error": "Arama sorgusu gerekli"}

        query = query.strip()

        # Check if database exists
        if not DB_PATH.exists():
            return {
                "success": True,
                "results": [],
                "count": 0,
                "query": query,
                "message": "Henüz not yok. İlk notunuzu oluşturun."
            }

        conn = _get_db_connection()
        try:
            results = []

            # Build FTS query based on search_in parameter
            if search_in == "title":
                fts_query = f'title:"{query}" OR title:{query}*'
            elif search_in == "content":
                fts_query = f'content:"{query}" OR content:{query}*'
            elif search_in == "tags":
                fts_query = f'tags:"{query}" OR tags:{query}*'
            else:
                # Search in all fields
                fts_query = f'"{query}" OR {query}*'

            # First try FTS search
            try:
                fts_sql = '''
                    SELECT notes_fts.id, notes_fts.title,
                           snippet(notes_fts, 2, '**', '**', '...', 50) as content_snippet,
                           notes_fts.tags, notes_fts.category,
                           bm25(notes_fts) as rank
                    FROM notes_fts
                    WHERE notes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                '''
                cursor = conn.execute(fts_sql, (fts_query, limit * 2))
                fts_results = cursor.fetchall()

                # Get full note info for FTS results
                for row in fts_results:
                    note_id = row["id"]

                    # Apply filters
                    note_cursor = conn.execute(
                        "SELECT * FROM notes WHERE id = ? AND is_deleted = 0",
                        (note_id,)
                    )
                    note = note_cursor.fetchone()

                    if not note:
                        continue

                    # Apply category filter
                    if category and note["category"] != category:
                        continue

                    # Apply tags filter
                    if tags:
                        if isinstance(tags, str):
                            tags_list = [t.strip() for t in tags.split(",")]
                        else:
                            tags_list = tags
                        note_tags = note["tags"].split(",") if note["tags"] else []
                        if not any(t in note_tags for t in tags_list):
                            continue

                    note_tags_list = note["tags"].split(",") if note["tags"] else []

                    results.append({
                        "id": note_id,
                        "title": note["title"],
                        "filename": note["filename"],
                        "category": note["category"],
                        "tags": [t.strip() for t in note_tags_list if t.strip()],
                        "snippet": row["content_snippet"],
                        "created_at": note["created_at"],
                        "updated_at": note["updated_at"],
                        "relevance": -row["rank"]  # BM25 returns negative scores
                    })

                    if len(results) >= limit:
                        break

            except sqlite3.OperationalError as e:
                logger.warning(f"FTS arama başarısız, LIKE ile devam ediliyor: {e}")

                # Fallback to LIKE search
                like_query = f"%{query}%"
                sql = '''
                    SELECT * FROM notes
                    WHERE is_deleted = 0
                    AND (title LIKE ? OR tags LIKE ?)
                '''
                params = [like_query, like_query]

                if category:
                    sql += " AND category = ?"
                    params.append(category)

                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()

                for row in rows:
                    note_tags = row["tags"].split(",") if row["tags"] else []

                    # Apply tags filter
                    if tags:
                        if isinstance(tags, str):
                            tags_list = [t.strip() for t in tags.split(",")]
                        else:
                            tags_list = tags
                        if not any(t in note_tags for t in tags_list):
                            continue

                    # Read content snippet from file
                    note_path = NOTES_DIR / row["filename"]
                    snippet = ""
                    if note_path.exists():
                        content = note_path.read_text(encoding="utf-8")
                        # Find query in content
                        lower_content = content.lower()
                        query_lower = query.lower()
                        idx = lower_content.find(query_lower)
                        if idx >= 0:
                            start = max(0, idx - 50)
                            end = min(len(content), idx + len(query) + 50)
                            snippet = "..." + content[start:end] + "..."

                    results.append({
                        "id": row["id"],
                        "title": row["title"],
                        "filename": row["filename"],
                        "category": row["category"],
                        "tags": [t.strip() for t in note_tags if t.strip()],
                        "snippet": snippet,
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "relevance": 1.0
                    })

            return {
                "success": True,
                "results": results,
                "count": len(results),
                "query": query,
                "search_in": search_in,
                "category_filter": category,
                "tags_filter": tags
            }

        finally:
            conn.close()

    except FileNotFoundError as e:
        return {
            "success": True,
            "results": [],
            "count": 0,
            "query": query,
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Not arama hatası: {e}")
        return {"success": False, "error": f"Arama yapılamadı: {str(e)}"}


async def get_note_categories() -> dict[str, Any]:
    """
    Mevcut kategorileri ve not sayılarını getir

    Returns:
        dict: Kategori listesi
    """
    try:
        if not DB_PATH.exists():
            return {
                "success": True,
                "categories": [],
                "count": 0
            }

        conn = _get_db_connection()
        try:
            cursor = conn.execute('''
                SELECT category, COUNT(*) as count
                FROM notes
                WHERE is_deleted = 0
                GROUP BY category
                ORDER BY count DESC
            ''')
            rows = cursor.fetchall()

            categories = [
                {"name": row["category"], "count": row["count"]}
                for row in rows
            ]

            return {
                "success": True,
                "categories": categories,
                "count": len(categories)
            }

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Kategori listeleme hatası: {e}")
        return {"success": False, "error": f"Kategoriler listelenemedi: {str(e)}"}


async def get_note_tags() -> dict[str, Any]:
    """
    Mevcut etiketleri ve kullanım sayılarını getir

    Returns:
        dict: Etiket listesi
    """
    try:
        if not DB_PATH.exists():
            return {
                "success": True,
                "tags": [],
                "count": 0
            }

        conn = _get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT tags FROM notes WHERE is_deleted = 0 AND tags != ''"
            )
            rows = cursor.fetchall()

            # Count tags
            tag_counts = {}
            for row in rows:
                tags = row["tags"].split(",")
                for tag in tags:
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            tags = [
                {"name": name, "count": count}
                for name, count in sorted(tag_counts.items(), key=lambda x: -x[1])
            ]

            return {
                "success": True,
                "tags": tags,
                "count": len(tags)
            }

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Etiket listeleme hatası: {e}")
        return {"success": False, "error": f"Etiketler listelenemedi: {str(e)}"}
