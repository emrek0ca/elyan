"""
Not Alma Sistemi - Note Taking System
CRUD operations, full-text search, and organization
"""

from .note_manager import (
    create_note,
    list_notes,
    update_note,
    delete_note,
    get_note
)
from .note_search import search_notes

__all__ = [
    "create_note",
    "list_notes",
    "update_note",
    "delete_note",
    "get_note",
    "search_notes"
]
