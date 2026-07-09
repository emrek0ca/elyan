"""Masaüstü kod-ajanı için okuma-tarafı dosya sistemi yetenekleri (Claude Code
benzeri): file_read, file_search, directory_tree. Hepsi READ-ONLY → izin
kapısı yok (permission modeli: read_only = dosya okuma / repo analizi).

Yazma/patch (file_write, file_patch) ayrı bir katman ve WRITE izin kapısından
geçer; burada yer almaz.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from actions._read_only_common import content_type_for
from runtime.capability_registry import SafeCapabilityError

# Kod-ajanı taramalarında atlanan klasörler (gürültü + performans).
IGNORE_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "dist", "build", "out", ".next", ".nuxt", "target", ".gradle",
        ".idea", ".vscode", "DerivedData", ".DS_Store", "Pods",
        "coverage", ".turbo", ".parcel-cache", "vendor",
    }
)

# Kesin gizli — hiçbir koşulda okunmaz/taranmaz.
_SENSITIVE_MARKERS = (
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "/.ssh/", "/.aws/credentials", "/.gnupg/",
    "/library/keychains/", ".keychain", ".pem", ".p12",
)

_MAX_READ_BYTES = 400_000
_MAX_SEARCH_RESULTS = 200
_MAX_SEARCH_FILE_BYTES = 2_000_000
_MAX_TREE_ENTRIES = 400
_DEFAULT_TREE_DEPTH = 3
_BINARY_SNIFF_BYTES = 4096


def _resolve_existing(path: str, *, want: str) -> Path:
    candidate = str(path or "").strip()
    if not candidate:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bir yol gerekli.")
    resolved = Path(candidate).expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved)
    resolved = resolved.resolve()
    lowered = str(resolved).lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        raise SafeCapabilityError("ACCESS_DENIED", "Bu yol gizli/hassas olduğu için okunamaz.")
    if not resolved.exists():
        raise SafeCapabilityError("FILE_NOT_FOUND", "Belirtilen yol bulunamadı.")
    if want == "file" and not resolved.is_file():
        raise SafeCapabilityError("INVALID_ARGUMENT", "Belirtilen yol bir dosya değil.")
    if want == "dir" and not resolved.is_dir():
        raise SafeCapabilityError("INVALID_ARGUMENT", "Belirtilen yol bir klasör değil.")
    return resolved


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    # Yüksek oranda kontrol karakteri → ikili varsay.
    text_chars = bytes(range(32, 127)) + b"\n\r\t\f\b"
    nontext = sum(1 for byte in sample if byte not in text_chars)
    return nontext / len(sample) > 0.30


def file_read(
    path: str,
    max_bytes: int = _MAX_READ_BYTES,
    start_line: int = 0,
    end_line: int = 0,
) -> dict[str, Any]:
    """Bir metin dosyasını güvenli şekilde okur. İsteğe bağlı satır aralığı."""
    resolved = _resolve_existing(path, want="file")
    try:
        cap = max(1, min(int(max_bytes or _MAX_READ_BYTES), _MAX_READ_BYTES))
    except (TypeError, ValueError):
        cap = _MAX_READ_BYTES

    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise SafeCapabilityError("READ_FAILED", "Dosya okunamadı.") from exc

    if _looks_binary(raw[:_BINARY_SNIFF_BYTES]):
        raise SafeCapabilityError(
            "UNSUPPORTED_FORMAT",
            "Bu dosya ikili (binary) görünüyor; metin olarak okunamaz.",
        )

    truncated = len(raw) > cap
    text = raw[:cap].decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    total_lines = len(all_lines)

    try:
        s = max(0, int(start_line or 0))
        e = int(end_line or 0)
    except (TypeError, ValueError):
        s, e = 0, 0
    if s or e:
        lo = max(0, s - 1) if s else 0
        hi = e if e else total_lines
        selected = all_lines[lo:hi]
        line_offset = lo + 1
    else:
        selected = all_lines
        line_offset = 1

    numbered = "\n".join(f"{line_offset + idx}\t{line}" for idx, line in enumerate(selected))
    note = ""
    if truncated:
        note = f"\n… (dosya {len(raw)} bayt, ilk {cap} bayt okundu)"

    return {
        "text": (numbered or "(boş dosya)") + note,
        "result": {
            "kind": "file_read",
            "path": str(resolved),
            "name": resolved.name,
            "totalLines": total_lines,
            "returnedLines": len(selected),
            "startLine": line_offset,
            "byteSize": len(raw),
            "truncated": truncated,
            "contentType": content_type_for(resolved),
        },
        "artifacts": [],
    }


def _iter_search_files(root: Path, glob: str) -> list[Path]:
    if glob:
        return [p for p in root.rglob(glob) if p.is_file()]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for name in filenames:
            files.append(Path(dirpath) / name)
    return files


def _search_with_ripgrep(query: str, root: Path, glob: str, *, regex: bool, case_sensitive: bool, limit: int) -> list[dict[str, Any]] | None:
    rg = shutil.which("rg")
    if not rg:
        return None
    argv = [rg, "--line-number", "--no-heading", "--color", "never", "--max-count", str(limit)]
    if not regex:
        argv.append("--fixed-strings")
    if not case_sensitive:
        argv.append("--ignore-case")
    for ignored in IGNORE_DIRS:
        argv += ["--glob", f"!{ignored}/"]
    if glob:
        argv += ["--glob", glob]
    argv += ["--", query, str(root)]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return None
    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_part, line_no, content = parts[0], parts[1], parts[2]
        if not line_no.isdigit():
            continue
        matches.append({"path": file_part, "line": int(line_no), "text": content.strip()[:400]})
        if len(matches) >= limit:
            break
    return matches


def _search_python(query: str, root: Path, glob: str, *, regex: bool, case_sensitive: bool, limit: int) -> list[dict[str, Any]]:
    if regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz regex deseni.") from exc
        predicate = lambda text: pattern.search(text) is not None
    else:
        needle = query if case_sensitive else query.lower()
        predicate = lambda text: (needle in (text if case_sensitive else text.lower()))

    matches: list[dict[str, Any]] = []
    for file_path in _iter_search_files(root, glob):
        try:
            if file_path.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                continue
            with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if predicate(line):
                        matches.append({"path": str(file_path), "line": line_no, "text": line.strip()[:400]})
                        if len(matches) >= limit:
                            return matches
        except (OSError, ValueError):
            continue
    return matches


def file_search(
    query: str,
    path: str = ".",
    glob: str = "",
    regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict[str, Any]:
    """Bir klasör ağacında dosya içeriğinde metin/regex arar (ripgrep varsa onu,
    yoksa saf Python taramasını kullanır)."""
    needle = str(query or "").strip()
    if not needle:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Arama terimi gerekli.")
    root = _resolve_existing(path or ".", want="dir")
    try:
        limit = max(1, min(int(max_results or 50), _MAX_SEARCH_RESULTS))
    except (TypeError, ValueError):
        limit = 50
    glob_pat = str(glob or "").strip()

    matches = _search_with_ripgrep(
        needle, root, glob_pat, regex=bool(regex), case_sensitive=bool(case_sensitive), limit=limit
    )
    engine = "ripgrep"
    if matches is None:
        engine = "python"
        matches = _search_python(
            needle, root, glob_pat, regex=bool(regex), case_sensitive=bool(case_sensitive), limit=limit
        )

    if not matches:
        text = f"'{needle}' için {root.name} altında eşleşme bulunamadı."
    else:
        lines = [f"{m['path']}:{m['line']}: {m['text']}" for m in matches]
        text = f"{len(matches)} eşleşme:\n" + "\n".join(lines)

    return {
        "text": text,
        "result": {
            "kind": "file_search",
            "query": needle,
            "root": str(root),
            "engine": engine,
            "regex": bool(regex),
            "matchCount": len(matches),
            "matches": matches,
        },
        "artifacts": [],
    }


def directory_tree(path: str = ".", max_depth: int = _DEFAULT_TREE_DEPTH, max_entries: int = _MAX_TREE_ENTRIES) -> dict[str, Any]:
    """Proje yapısını (klasör ağacını) çıkarır; gürültülü klasörleri atlar."""
    root = _resolve_existing(path or ".", want="dir")
    try:
        depth_cap = max(1, min(int(max_depth or _DEFAULT_TREE_DEPTH), 8))
    except (TypeError, ValueError):
        depth_cap = _DEFAULT_TREE_DEPTH
    try:
        entry_cap = max(1, min(int(max_entries or _MAX_TREE_ENTRIES), _MAX_TREE_ENTRIES))
    except (TypeError, ValueError):
        entry_cap = _MAX_TREE_ENTRIES

    lines: list[str] = [f"{root.name}/"]
    entry_count = 0
    truncated = False

    def walk(directory: Path, prefix: str, depth: int) -> None:
        nonlocal entry_count, truncated
        if depth > depth_cap or truncated:
            return
        try:
            children = sorted(
                (c for c in directory.iterdir() if c.name not in IGNORE_DIRS),
                key=lambda c: (c.is_file(), c.name.lower()),
            )
        except OSError:
            return
        for index, child in enumerate(children):
            if entry_count >= entry_cap:
                truncated = True
                return
            connector = "└── " if index == len(children) - 1 else "├── "
            suffix = "/" if child.is_dir() else ""
            lines.append(f"{prefix}{connector}{child.name}{suffix}")
            entry_count += 1
            if child.is_dir():
                extension = "    " if index == len(children) - 1 else "│   "
                walk(child, prefix + extension, depth + 1)

    walk(root, "", 1)
    if truncated:
        lines.append(f"… ({entry_cap} giriş sınırına ulaşıldı)")

    return {
        "text": "\n".join(lines),
        "result": {
            "kind": "directory_tree",
            "root": str(root),
            "entryCount": entry_count,
            "depth": depth_cap,
            "truncated": truncated,
        },
        "artifacts": [],
    }
