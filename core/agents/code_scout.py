from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("code_scout")

_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "Pods",
    "DerivedData",
}

_LANGUAGE_SUFFIXES = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _language_for(path: Path) -> str:
    return _LANGUAGE_SUFFIXES.get(path.suffix.lower(), "text")


@dataclass(slots=True)
class ScoutFinding:
    path: str
    language: str
    score: int
    line_count: int
    preview: str
    matches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "score": self.score,
            "line_count": self.line_count,
            "preview": self.preview,
            "matches": list(self.matches),
        }


class CodeScoutAgent:
    """Deterministic workspace scout used by the DevAgent orchestrator."""

    def __init__(self, *, max_preview_chars: int = 240, max_scan_bytes: int = 128_000) -> None:
        self.max_preview_chars = max(80, int(max_preview_chars or 240))
        self.max_scan_bytes = max(8_192, int(max_scan_bytes or 128_000))

    @staticmethod
    def _should_skip(path: Path, root: Path) -> bool:
        try:
            relative_parts = path.relative_to(root).parts
        except Exception:
            relative_parts = path.parts
        for part in relative_parts[:-1]:
            if part in _SKIP_DIRS or part.startswith("."):
                return True
        return path.name.startswith(".") and path.suffix == ""

    def scan(self, root: str | Path, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            return {
                "workspace": str(root_path),
                "query": str(query or ""),
                "matches": 0,
                "scanned_files": 0,
                "language_breakdown": {},
                "findings": [],
            }

        tokens = [token for token in re.split(r"\s+", _normalize_text(query)) if token]
        result_limit = max(1, int(limit or 20))
        findings: list[ScoutFinding] = []
        language_breakdown: Counter[str] = Counter()
        scanned_files = 0

        for path in root_path.rglob("*"):
            if len(findings) >= result_limit:
                break
            if not path.is_file() or self._should_skip(path, root_path):
                continue
            scanned_files += 1

            language = _language_for(path)
            language_breakdown[language] += 1

            try:
                stat = path.stat()
            except Exception:
                stat = None

            content = ""
            if stat is not None and stat.st_size <= self.max_scan_bytes:
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    content = ""

            haystack_path = _normalize_text(path.as_posix())
            haystack_content = _normalize_text(content)
            matches: list[str] = []
            score = 0
            if tokens:
                for token in tokens:
                    if token in haystack_path:
                        score += 3
                        matches.append(f"path:{token}")
                    if token in haystack_content:
                        score += 2
                        matches.append(f"content:{token}")
            else:
                score = 1

            if tokens and score <= 0:
                continue

            preview = "\n".join(content.splitlines()[:4]).strip()
            if len(preview) > self.max_preview_chars:
                preview = preview[: self.max_preview_chars - 3] + "..."

            findings.append(
                ScoutFinding(
                    path=str(path.relative_to(root_path)),
                    language=language,
                    score=score,
                    line_count=len(content.splitlines()) if content else 0,
                    preview=preview,
                    matches=sorted(set(matches)),
                )
            )

        findings.sort(key=lambda item: (item.score, item.line_count, item.path), reverse=True)
        selected = findings[:result_limit]
        return {
            "workspace": str(root_path),
            "query": str(query or ""),
            "matches": len(selected),
            "scanned_files": scanned_files,
            "language_breakdown": dict(sorted(language_breakdown.items())),
            "findings": [item.to_dict() for item in selected],
        }


__all__ = ["CodeScoutAgent", "ScoutFinding"]
