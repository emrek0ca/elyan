from __future__ import annotations

import mimetypes
from pathlib import Path

from runtime.capability_registry import SafeCapabilityError


READ_MODES = {"read", "summary", "bullets"}


def workspace_root() -> Path:
    return Path.cwd().resolve()


def is_explicit_path_value(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    return raw.startswith(("~", "/", "\\")) or (
        len(raw) > 2 and raw[1] == ":" and raw[2] in {"/", "\\"}
    )


def ensure_allowed_path(
    raw_path: str,
    *,
    allowed_suffixes: set[str] | None = None,
    selected_paths: list[str] | None = None,
    root_resolver=workspace_root,
) -> Path:
    candidate = str(raw_path or "").strip()
    if not candidate:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Dosya yolu gerekli.")

    resolved = Path(candidate).expanduser()
    if not resolved.is_absolute():
        resolved = (root_resolver() / resolved).resolve()
    else:
        resolved = resolved.resolve()

    if not resolved.exists() or not resolved.is_file():
        raise SafeCapabilityError("FILE_NOT_FOUND", "İstenen dosya bulunamadı.")

    root = root_resolver()
    selected_resolved: set[Path] = set()
    for item in selected_paths or []:
        try:
            selected_resolved.add(Path(str(item or "").strip()).expanduser().resolve())
        except Exception:
            continue

    allowed = False
    try:
        resolved.relative_to(root)
        allowed = True
    except ValueError:
        allowed = resolved in selected_resolved

    if not allowed:
        raise SafeCapabilityError(
            "ACCESS_DENIED",
            "Dosya yalnızca seçilmiş hedef veya izinli çalışma alanı içinden okunabilir.",
        )

    if allowed_suffixes is not None:
        suffix = resolved.suffix.lower()
        if suffix not in allowed_suffixes:
            raise SafeCapabilityError(
                "UNSUPPORTED_FORMAT",
                "Bu dosya türü bu özellik için desteklenmiyor.",
            )
    return resolved


def ensure_mode(value: str, *, allowed: set[str] = READ_MODES) -> str:
    mode = str(value or "read").strip().lower() or "read"
    if mode not in allowed:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz okuma modu.")
    return mode


def content_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    return "application/octet-stream"


def summarize_text(text: str, *, max_chars: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def bulletize_text(text: str, *, limit: int = 6) -> list[str]:
    cleaned = str(text or "").replace("\r", "\n")
    chunks: list[str] = []
    for line in cleaned.splitlines():
        candidate = " ".join(line.split()).strip(" -•\t")
        if not candidate:
            continue
        chunks.append(candidate)
        if len(chunks) >= limit:
            break
    if chunks:
        return chunks

    sentence_chunks = [
        " ".join(part.split()).strip()
        for part in cleaned.replace("!", ".").replace("?", ".").split(".")
        if " ".join(part.split()).strip()
    ]
    return sentence_chunks[:limit]


def preview_text(text: str, *, limit: int = 8000) -> str:
    payload = str(text or "").strip()
    if len(payload) <= limit:
        return payload
    return payload[: limit - 1].rstrip() + "…"
