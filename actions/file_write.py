"""Masaüstü kod-ajanı için YAZMA-tarafı dosya yetenekleri: file_write, file_patch.

Bunlar mutasyon yapar → `safety_policy.WRITE_CAPABILITIES` kapısından geçer
(onaysız çalışmaz; executor onaylı planlarda `_confirmed=True` enjekte eder).

file_patch sözleşmesi bilinçli olarak **çıpalı bul/değiştir** (old_string →
new_string), unified-diff üretimi değil — bir LLM'in güvenilir üretebileceği
en sağlam biçim (Claude Code'un Edit aracıyla aynı model).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import content_type_for, is_explicit_path_value
from actions.filesystem import _SENSITIVE_MARKERS, _looks_binary
from runtime.capability_registry import SafeCapabilityError

_MAX_WRITE_BYTES = 5_000_000
_DIFF_CONTEXT = 3


def _blocked_sensitive(path: Path) -> bool:
    lowered = str(path).lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def _resolve_write_path(raw_path: str, *, must_exist: bool) -> Path:
    candidate = str(raw_path or "").strip()
    if not candidate:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bir dosya yolu gerekli.")
    resolved = Path(candidate).expanduser()
    explicit = is_explicit_path_value(candidate)
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved)
    resolved = resolved.resolve()

    if _blocked_sensitive(resolved):
        raise SafeCapabilityError("ACCESS_DENIED", "Bu yol gizli/hassas; yazılamaz.")

    # Açık yol (~,/) serbest; aksi halde yalnız çalışma alanı (cwd) altına yaz.
    if not explicit:
        root = Path.cwd().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SafeCapabilityError(
                "ACCESS_DENIED",
                "Dosya yalnızca açık yol veya çalışma alanı içine yazılabilir.",
            ) from exc

    if must_exist:
        if not resolved.exists():
            raise SafeCapabilityError("FILE_NOT_FOUND", "Düzenlenecek dosya bulunamadı.")
        if not resolved.is_file():
            raise SafeCapabilityError("INVALID_ARGUMENT", "Belirtilen yol bir dosya değil.")
    return resolved


def _unified_preview(before: str, after: str, name: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{name}",
        tofile=f"b/{name}",
        n=_DIFF_CONTEXT,
        lineterm="",
    )
    lines = list(diff)
    text = "\n".join(lines[:400])
    if len(lines) > 400:
        text += "\n… (diff kısaltıldı)"
    return text


def file_write(
    path: str,
    content: str = "",
    overwrite: bool = False,
    _confirmed: bool = False,
) -> dict[str, Any]:
    """Bir metin dosyası oluşturur veya (overwrite=True ile) üzerine yazar."""
    body = "" if content is None else str(content)
    if len(body.encode("utf-8", errors="ignore")) > _MAX_WRITE_BYTES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "İçerik izin verilen boyutu aşıyor.")

    resolved = _resolve_write_path(path, must_exist=False)
    existed = resolved.exists()
    if existed and not overwrite:
        raise SafeCapabilityError(
            "FILE_EXISTS",
            "Hedef dosya zaten var. Üzerine yazmak için overwrite=true gerekiyor.",
        )

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise SafeCapabilityError("WRITE_FAILED", "Dosya yazılamadı.") from exc

    line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
    verb = "güncellendi" if existed else "oluşturuldu"
    return {
        "text": f"{resolved.name} {verb} ({line_count} satır).",
        "result": {
            "kind": "file_write",
            "path": str(resolved),
            "name": resolved.name,
            "created": not existed,
            "overwritten": existed,
            "byteSize": len(body.encode("utf-8", errors="ignore")),
            "lineCount": line_count,
            "contentType": content_type_for(resolved),
        },
        "artifacts": [
            {
                "kind": "file",
                "name": resolved.name,
                "path": str(resolved),
                "contentType": content_type_for(resolved),
            }
        ],
    }


def file_patch(
    path: str,
    old_string: str = "",
    new_string: str = "",
    replace_all: bool = False,
    _confirmed: bool = False,
) -> dict[str, Any]:
    """Var olan bir dosyada çıpalı bul/değiştir uygular (old_string → new_string).
    old_string benzersiz olmalı (replace_all=True değilse)."""
    anchor = "" if old_string is None else str(old_string)
    replacement = "" if new_string is None else str(new_string)
    if not anchor:
        raise SafeCapabilityError("INVALID_ARGUMENT", "old_string (çıpa) gerekli.")
    if anchor == replacement:
        raise SafeCapabilityError("INVALID_ARGUMENT", "old_string ve new_string aynı; değişiklik yok.")

    resolved = _resolve_write_path(path, must_exist=True)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise SafeCapabilityError("READ_FAILED", "Dosya okunamadı.") from exc
    if _looks_binary(raw[:4096]):
        raise SafeCapabilityError("UNSUPPORTED_FORMAT", "İkili dosya yamalanamaz.")

    before = raw.decode("utf-8", errors="replace")
    occurrences = before.count(anchor)
    if occurrences == 0:
        raise SafeCapabilityError("PATCH_ANCHOR_NOT_FOUND", "old_string dosyada bulunamadı.")
    if occurrences > 1 and not replace_all:
        raise SafeCapabilityError(
            "PATCH_ANCHOR_AMBIGUOUS",
            f"old_string {occurrences} kez geçiyor; benzersiz yap veya replace_all=true ver.",
        )

    if replace_all:
        after = before.replace(anchor, replacement)
        replacements = occurrences
    else:
        after = before.replace(anchor, replacement, 1)
        replacements = 1

    if after == before:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Yama sonucu değişiklik üretmedi.")
    if len(after.encode("utf-8", errors="ignore")) > _MAX_WRITE_BYTES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Sonuç izin verilen boyutu aşıyor.")

    try:
        resolved.write_text(after, encoding="utf-8")
    except OSError as exc:
        raise SafeCapabilityError("WRITE_FAILED", "Dosya yazılamadı.") from exc

    preview = _unified_preview(before, after, resolved.name)
    return {
        "text": f"{resolved.name} yamalandı ({replacements} değişiklik).\n{preview}",
        "result": {
            "kind": "file_patch",
            "path": str(resolved),
            "name": resolved.name,
            "replacements": replacements,
            "replaceAll": bool(replace_all),
            "diffPreview": preview,
            "byteSize": len(after.encode("utf-8", errors="ignore")),
        },
        "artifacts": [
            {
                "kind": "file",
                "name": resolved.name,
                "path": str(resolved),
                "contentType": content_type_for(resolved),
            }
        ],
    }
