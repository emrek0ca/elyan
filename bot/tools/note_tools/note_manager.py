"""
Not Yöneticisi - Note Manager
CRUD operasyonları: oluşturma, listeleme, güncelleme, silme
"""

import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any
from utils.logger import get_logger

logger = get_logger("note_manager")

# Notes storage location
NOTES_DIR = Path.home() / "Documents" / "BotNotes"
DB_PATH = NOTES_DIR / ".notes_index.db"


def _ensure_notes_dir():
    """Notlar dizininin var olduğundan emin ol"""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


def _get_db_connection() -> sqlite3.Connection:
    """SQLite veritabanı bağlantısı al"""
    _ensure_notes_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Create tables if not exist
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            tags TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            id,
            title,
            content,
            tags,
            category,
            content='',
            tokenize='unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);
        CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);
        CREATE INDEX IF NOT EXISTS idx_notes_deleted ON notes(is_deleted);
    ''')
    conn.commit()
    return conn


def _generate_note_id() -> str:
    """Benzersiz not ID'si oluştur"""
    return f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _sanitize_filename(title: str) -> str:
    """Başlığı dosya adı olarak kullanılabilir hale getir"""
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    filename = title
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    # Limit length
    if len(filename) > 100:
        filename = filename[:100]
    return filename.strip() or "untitled"


async def create_note(
    title: str,
    content: str,
    tags: list[str] | str | None = None,
    category: str = "general"
) -> dict[str, Any]:
    """
    Yeni not oluştur

    Args:
        title: Not başlığı
        content: Not içeriği
        tags: Etiketler (liste veya virgülle ayrılmış string)
        category: Kategori (general, work, personal, ideas, todo)

    Returns:
        dict: Oluşturulan not bilgileri
    """
    try:
        if not title or not title.strip():
            return {"success": False, "error": "Not başlığı gerekli"}

        if not content:
            content = ""

        # Process tags
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif tags is None:
            tags = []

        tags_str = ",".join(tags) if tags else ""

        # Generate ID and filename
        note_id = _generate_note_id()
        safe_filename = _sanitize_filename(title)
        filename = f"{safe_filename}.md"

        # Ensure unique filename
        counter = 1
        while (NOTES_DIR / filename).exists():
            filename = f"{safe_filename}_{counter}.md"
            counter += 1

        # Create markdown content
        now = datetime.now()
        md_content = f"""---
id: {note_id}
title: {title}
category: {category}
tags: {', '.join(tags)}
created: {now.isoformat()}
updated: {now.isoformat()}
---

# {title}

{content}
"""

        # Write file
        _ensure_notes_dir()
        note_path = NOTES_DIR / filename
        note_path.write_text(md_content, encoding="utf-8")

        # Update database
        conn = _get_db_connection()
        try:
            conn.execute('''
                INSERT INTO notes (id, title, filename, category, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (note_id, title, filename, category, tags_str, now.isoformat(), now.isoformat()))

            # Update FTS index
            conn.execute('''
                INSERT INTO notes_fts (id, title, content, tags, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (note_id, title, content, tags_str, category))

            conn.commit()
        finally:
            conn.close()

        logger.info(f"Not oluşturuldu: {title} ({note_id})")

        return {
            "success": True,
            "id": note_id,
            "title": title,
            "filename": filename,
            "category": category,
            "tags": tags,
            "path": str(note_path),
            "created_at": now.isoformat(),
            "message": f"Not oluşturuldu: {title}"
        }

    except Exception as e:
        logger.error(f"Not oluşturma hatası: {e}")
        return {"success": False, "error": f"Not oluşturulamadı: {str(e)}"}


async def list_notes(
    category: str | None = None,
    tags: list[str] | str | None = None,
    limit: int = 50,
    include_deleted: bool = False
) -> dict[str, Any]:
    """
    Notları listele

    Args:
        category: Filtrelenecek kategori
        tags: Filtrelenecek etiketler
        limit: Maksimum sonuç sayısı
        include_deleted: Silinmiş notları dahil et

    Returns:
        dict: Not listesi
    """
    try:
        conn = _get_db_connection()
        try:
            query = "SELECT * FROM notes WHERE 1=1"
            params = []

            if not include_deleted:
                query += " AND is_deleted = 0"

            if category:
                query += " AND category = ?"
                params.append(category)

            if tags:
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]
                for tag in tags:
                    query += " AND tags LIKE ?"
                    params.append(f"%{tag}%")

            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            notes = []
            for row in rows:
                note_tags = row["tags"].split(",") if row["tags"] else []
                notes.append({
                    "id": row["id"],
                    "title": row["title"],
                    "filename": row["filename"],
                    "category": row["category"],
                    "tags": [t.strip() for t in note_tags if t.strip()],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "is_deleted": bool(row["is_deleted"])
                })

            return {
                "success": True,
                "notes": notes,
                "count": len(notes),
                "category_filter": category,
                "tags_filter": tags
            }

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Not listeleme hatası: {e}")
        return {"success": False, "error": f"Notlar listelenemedi: {str(e)}"}


async def get_note(note_id: str) -> dict[str, Any]:
    """
    Tek bir notu getir

    Args:
        note_id: Not ID'si veya başlık

    Returns:
        dict: Not detayları ve içeriği
    """
    try:
        conn = _get_db_connection()
        try:
            # Try by ID first
            cursor = conn.execute(
                "SELECT * FROM notes WHERE id = ? AND is_deleted = 0",
                (note_id,)
            )
            row = cursor.fetchone()

            # Try by title if not found
            if not row:
                cursor = conn.execute(
                    "SELECT * FROM notes WHERE title LIKE ? AND is_deleted = 0 LIMIT 1",
                    (f"%{note_id}%",)
                )
                row = cursor.fetchone()

            if not row:
                return {"success": False, "error": f"Not bulunamadı: {note_id}"}

            # Read content from file
            note_path = NOTES_DIR / row["filename"]
            content = ""
            if note_path.exists():
                full_content = note_path.read_text(encoding="utf-8")
                # Extract content after frontmatter
                if "---" in full_content:
                    parts = full_content.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                    else:
                        content = full_content
                else:
                    content = full_content

            note_tags = row["tags"].split(",") if row["tags"] else []

            return {
                "success": True,
                "id": row["id"],
                "title": row["title"],
                "content": content,
                "filename": row["filename"],
                "category": row["category"],
                "tags": [t.strip() for t in note_tags if t.strip()],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "path": str(note_path)
            }

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Not getirme hatası: {e}")
        return {"success": False, "error": f"Not getirilemedi: {str(e)}"}


async def update_note(
    note_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | str | None = None,
    category: str | None = None,
    append: bool = False
) -> dict[str, Any]:
    """
    Notu güncelle

    Args:
        note_id: Not ID'si veya başlık
        title: Yeni başlık
        content: Yeni içerik
        tags: Yeni etiketler
        category: Yeni kategori
        append: True ise içeriği sona ekle

    Returns:
        dict: Güncelleme sonucu
    """
    try:
        # Get existing note
        existing = await get_note(note_id)
        if not existing.get("success"):
            return existing

        actual_id = existing["id"]
        old_filename = existing["filename"]

        # Prepare new values
        new_title = title if title else existing["title"]
        new_category = category if category else existing["category"]

        if tags is not None:
            if isinstance(tags, str):
                new_tags = [t.strip() for t in tags.split(",") if t.strip()]
            else:
                new_tags = tags
        else:
            new_tags = existing["tags"]

        new_tags_str = ",".join(new_tags)

        # Handle content
        if content is not None:
            if append:
                new_content = existing["content"] + "\n\n" + content
            else:
                new_content = content
        else:
            new_content = existing["content"]

        # Update file
        now = datetime.now()
        md_content = f"""---
id: {actual_id}
title: {new_title}
category: {new_category}
tags: {', '.join(new_tags)}
created: {existing['created_at']}
updated: {now.isoformat()}
---

# {new_title}

{new_content}
"""

        note_path = NOTES_DIR / old_filename

        # Handle title change (rename file)
        if title and title != existing["title"]:
            safe_filename = _sanitize_filename(new_title)
            new_filename = f"{safe_filename}.md"
            counter = 1
            while (NOTES_DIR / new_filename).exists() and new_filename != old_filename:
                new_filename = f"{safe_filename}_{counter}.md"
                counter += 1

            new_path = NOTES_DIR / new_filename
            if old_filename != new_filename:
                note_path.rename(new_path)
                note_path = new_path
                old_filename = new_filename

        note_path.write_text(md_content, encoding="utf-8")

        # Update database
        conn = _get_db_connection()
        try:
            conn.execute('''
                UPDATE notes
                SET title = ?, filename = ?, category = ?, tags = ?, updated_at = ?
                WHERE id = ?
            ''', (new_title, old_filename, new_category, new_tags_str, now.isoformat(), actual_id))

            # Update FTS
            conn.execute("DELETE FROM notes_fts WHERE id = ?", (actual_id,))
            conn.execute('''
                INSERT INTO notes_fts (id, title, content, tags, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (actual_id, new_title, new_content, new_tags_str, new_category))

            conn.commit()
        finally:
            conn.close()

        logger.info(f"Not güncellendi: {new_title} ({actual_id})")

        return {
            "success": True,
            "id": actual_id,
            "title": new_title,
            "filename": old_filename,
            "category": new_category,
            "tags": new_tags,
            "updated_at": now.isoformat(),
            "path": str(note_path),
            "message": f"Not güncellendi: {new_title}"
        }

    except Exception as e:
        logger.error(f"Not güncelleme hatası: {e}")
        return {"success": False, "error": f"Not güncellenemedi: {str(e)}"}


async def delete_note(
    note_id: str,
    permanent: bool = False
) -> dict[str, Any]:
    """
    Notu sil

    Args:
        note_id: Not ID'si veya başlık
        permanent: True ise kalıcı sil, False ise soft delete

    Returns:
        dict: Silme sonucu
    """
    try:
        # Get existing note
        existing = await get_note(note_id)
        if not existing.get("success"):
            return existing

        actual_id = existing["id"]
        filename = existing["filename"]
        title = existing["title"]

        conn = _get_db_connection()
        try:
            if permanent:
                # Delete file
                note_path = NOTES_DIR / filename
                if note_path.exists():
                    note_path.unlink()

                # Delete from database
                conn.execute("DELETE FROM notes WHERE id = ?", (actual_id,))
                conn.execute("DELETE FROM notes_fts WHERE id = ?", (actual_id,))
                message = f"Not kalıcı olarak silindi: {title}"
            else:
                # Soft delete
                conn.execute(
                    "UPDATE notes SET is_deleted = 1, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), actual_id)
                )
                message = f"Not silindi: {title}"

            conn.commit()
        finally:
            conn.close()

        logger.info(f"Not silindi: {title} ({actual_id}) - permanent={permanent}")

        return {
            "success": True,
            "id": actual_id,
            "title": title,
            "permanent": permanent,
            "message": message
        }

    except Exception as e:
        logger.error(f"Not silme hatası: {e}")
        return {"success": False, "error": f"Not silinemedi: {str(e)}"}
