from __future__ import annotations

import re
from pathlib import Path

from actions._read_only_common import content_type_for, is_explicit_path_value, preview_text, workspace_root
from runtime.capability_registry import SafeCapabilityError


DEFAULT_OUTPUT_DIRNAME = "elyan_output"


def output_root(root_resolver=workspace_root) -> Path:
    return root_resolver() / DEFAULT_OUTPUT_DIRNAME


def slugify_filename(value: str, *, fallback: str = "untitled") -> str:
    cleaned = " ".join(str(value or "").strip().split()).lower()
    cleaned = (
        cleaned.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:64] or fallback


def ensure_allowed_output_path(
    raw_path: str,
    *,
    extension: str,
    overwrite: bool = False,
    hint: str = "",
    root_resolver=workspace_root,
) -> Path:
    suffix = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    candidate = str(raw_path or "").strip()
    if candidate:
        resolved = Path(candidate).expanduser()
        if not resolved.suffix:
            resolved = resolved.with_suffix(suffix)
        if not resolved.is_absolute():
            resolved = (root_resolver() / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if not is_explicit_path_value(candidate):
            root = root_resolver().resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise SafeCapabilityError(
                    "ACCESS_DENIED",
                    "Dosya yalnızca açık yol veya izinli çalışma alanı içine yazılabilir.",
                ) from exc
    else:
        filename = f"{slugify_filename(hint or 'elyan-output')}{suffix}"
        resolved = (output_root(root_resolver) / filename).resolve()

    if resolved.suffix.lower() != suffix:
        resolved = resolved.with_suffix(suffix)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and not overwrite:
        raise SafeCapabilityError(
            "FILE_EXISTS",
            "Hedef dosya zaten var. Üzerine yazmak için açık onay ve overwrite=true gerekiyor.",
        )
    return resolved


def normalize_source_context(value: str, *, max_chars: int = 320) -> str:
    return preview_text(" ".join(str(value or "").split()), limit=max_chars)


def artifact_payload(path: Path) -> dict[str, str]:
    return {
        "kind": "file",
        "name": path.name,
        "path": str(path),
        "contentType": content_type_for(path),
    }
