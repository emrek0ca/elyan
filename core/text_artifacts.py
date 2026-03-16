from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator


TEXT_SUFFIXES = (".txt", ".md")
DEFAULT_SAVE_MARKERS = ("kaydet", "save", "result.json", "summary.txt", "summary.md", "dosyaya yaz")


def preferred_text_path(path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() == ".md":
        return target.with_suffix(".txt")
    return target


def text_variants(path: str | Path) -> tuple[Path, ...]:
    target = Path(path)
    if target.suffix.lower() in TEXT_SUFFIXES:
        base = target.with_suffix("")
        return tuple(base.with_suffix(suffix) for suffix in TEXT_SUFFIXES)
    return (preferred_text_path(target),)


def existing_text_path(path: str | Path) -> Path:
    for candidate in text_variants(path):
        if candidate.exists():
            return candidate
    return preferred_text_path(path)


def default_summary_path(result_path: str | Path) -> str:
    target = Path(str(result_path or "result.json")).expanduser()
    if not target.name:
        target = target / "result.json"
    return str(preferred_text_path(target.with_name("summary.txt")))


def write_text_artifact(run_dir: str | Path, relative_path: str, content: str) -> str:
    target = preferred_text_path(Path(str(run_dir or ".")).expanduser().resolve() / relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content or ""), encoding="utf-8")
    return str(target)


def write_json_artifact(run_dir: str | Path, relative_path: str, payload: Dict[str, Any]) -> str:
    target = Path(str(run_dir or ".")).expanduser().resolve() / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def iter_existing_text_paths(paths: Iterable[str | Path]) -> Iterator[Path]:
    for path in list(paths or []):
        yield existing_text_path(path)


__all__ = [
    "TEXT_SUFFIXES",
    "DEFAULT_SAVE_MARKERS",
    "default_summary_path",
    "existing_text_path",
    "iter_existing_text_paths",
    "preferred_text_path",
    "text_variants",
    "write_json_artifact",
    "write_text_artifact",
]
