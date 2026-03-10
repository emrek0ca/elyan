from __future__ import annotations

import os
import tempfile
from pathlib import Path

from config.settings import ELYAN_DIR


def _unique_paths(candidates: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for raw in candidates:
        try:
            resolved = str(raw.expanduser())
        except Exception:
            continue
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        out.append(Path(resolved))
    return out


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".elyan_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def resolve_elyan_data_dir() -> Path:
    env_path = str(os.getenv("ELYAN_DATA_DIR", "") or "").strip()
    candidates = _unique_paths(
        [
            Path(env_path).expanduser() if env_path else (Path.home() / ".elyan"),
            Path.home() / ".elyan",
            ELYAN_DIR,
            Path.cwd() / ".elyan",
            Path(tempfile.gettempdir()) / "elyan",
        ]
    )
    for candidate in candidates:
        if _ensure_writable_dir(candidate):
            return candidate.resolve()
    fallback = (Path(tempfile.gettempdir()) / "elyan").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _resolve_named_root(env_name: str, leaf: str) -> Path:
    env_path = str(os.getenv(env_name, "") or "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if _ensure_writable_dir(candidate):
            return candidate.resolve()
    root = resolve_elyan_data_dir() / leaf
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolve_runs_root() -> Path:
    return _resolve_named_root("ELYAN_RUNS_DIR", "runs")


def resolve_proofs_root() -> Path:
    return _resolve_named_root("ELYAN_PROOFS_DIR", "proofs")


__all__ = ["resolve_elyan_data_dir", "resolve_runs_root", "resolve_proofs_root"]
