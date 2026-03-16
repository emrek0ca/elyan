from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


ALLOWED_MARKDOWN_PATHS = frozenset({"PROGRESS.md"})
IGNORED_PREFIXES = (".git/", "venv/", ".venv/")


def normalize_repo_path(path: str | Path) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def is_allowed_markdown_path(path: str | Path) -> bool:
    normalized = normalize_repo_path(path)
    if not normalized.lower().endswith(".md"):
        return True
    if any(normalized.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return True
    return normalized in ALLOWED_MARKDOWN_PATHS


def find_disallowed_markdown_paths(paths: Iterable[str | Path]) -> List[str]:
    blocked: List[str] = []
    seen: set[str] = set()
    for path in list(paths or []):
        normalized = normalize_repo_path(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if not is_allowed_markdown_path(normalized):
            blocked.append(normalized)
    return blocked


__all__ = [
    "ALLOWED_MARKDOWN_PATHS",
    "IGNORED_PREFIXES",
    "find_disallowed_markdown_paths",
    "is_allowed_markdown_path",
    "normalize_repo_path",
]
