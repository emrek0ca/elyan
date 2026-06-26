from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from actions._read_only_common import (
    bulletize_text,
    content_type_for,
    ensure_allowed_path,
    ensure_mode,
    preview_text,
    summarize_text,
    workspace_root,
)
from runtime.capability_registry import SafeCapabilityError

_DIRECT_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_STRUCTURED_SUFFIXES = {".json", ".csv"}
_MARKITDOWN_SUFFIXES = {".docx", ".doc", ".pptx", ".xlsx", ".html", ".htm", ".rtf"}
_ALLOWED_SUFFIXES = _DIRECT_TEXT_SUFFIXES | _STRUCTURED_SUFFIXES | _MARKITDOWN_SUFFIXES | {".pdf"}


def _workspace_root() -> Path:
    return workspace_root()


def _text_from_markitdown(path: Path) -> str:
    from markitdown import MarkItDown  # type: ignore[reportMissingImports]

    converter = MarkItDown()
    converted = converter.convert(str(path))
    text = str(getattr(converted, "text_content", "") or "").strip()
    if not text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "Belgede okunabilir metin bulunamadı.")
    return text


def _text_from_mammoth(path: Path) -> str:
    import mammoth  # type: ignore[reportMissingImports]

    with path.open("rb") as handle:
        result = mammoth.extract_raw_text(handle)
    text = str(getattr(result, "value", "") or "").strip()
    if not text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "Belgede okunabilir metin bulunamadı.")
    return text


def _text_from_pymupdf(path: Path) -> tuple[str, int]:
    import fitz  # type: ignore[reportMissingImports]

    document = fitz.open(path)
    try:
        parts = [str(page.get_text("text") or "").strip() for page in document]
        text = "\n\n".join(part for part in parts if part).strip()
        if not text:
            raise SafeCapabilityError("EMPTY_DOCUMENT", "PDF içinde okunabilir metin bulunamadı.")
        return text, int(document.page_count or 0)
    finally:
        document.close()


def _text_from_pypdf(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader  # type: ignore[reportMissingImports]

    reader = PdfReader(str(path))
    parts = [str(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(part for part in parts if part).strip()
    if not text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "PDF içinde okunabilir metin bulunamadı.")
    return text, len(reader.pages)


def _text_from_json(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _text_from_csv(path: Path, *, row_limit: int = 20) -> str:
    rows: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for index, row in enumerate(reader):
            rows.append(", ".join(cell.strip() for cell in row))
            if index + 1 >= row_limit:
                break
    return "\n".join(row for row in rows if row.strip()).strip()


def _try_text_extractors(
    extractors: list[tuple[str, Any]],
) -> tuple[str, int | None, str]:
    last_empty_error: SafeCapabilityError | None = None
    missing_dependencies: list[str] = []
    for backend, extractor in extractors:
        try:
            extracted = extractor()
        except ModuleNotFoundError as exc:
            missing_dependencies.append(str(exc))
            continue
        except SafeCapabilityError as exc:
            if exc.code == "EMPTY_DOCUMENT":
                last_empty_error = exc
                continue
            raise

        if isinstance(extracted, tuple):
            text, pages = extracted
        else:
            text, pages = extracted, None
        normalized = str(text or "").strip()
        if normalized:
            return normalized, pages, backend
        last_empty_error = SafeCapabilityError("EMPTY_DOCUMENT", "Belgede okunabilir metin bulunamadı.")

    if last_empty_error is not None:
        raise last_empty_error
    if missing_dependencies:
        raise ModuleNotFoundError(", ".join(missing_dependencies))
    raise SafeCapabilityError("EMPTY_DOCUMENT", "Belgede okunabilir metin bulunamadı.")


def _extract_document_content(path: Path) -> tuple[str, int | None, str]:
    suffix = path.suffix.lower()
    if suffix in _DIRECT_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8"), None, "plain_text"
    if suffix == ".json":
        return _text_from_json(path), None, "json"
    if suffix == ".csv":
        return _text_from_csv(path), None, "csv"
    if suffix == ".pdf":
        return _try_text_extractors([
            ("pymupdf", lambda: _text_from_pymupdf(path)),
            ("pypdf", lambda: _text_from_pypdf(path)),
            ("markitdown", lambda: (_text_from_markitdown(path), None)),
        ])
    if suffix == ".docx":
        return _try_text_extractors([
            ("mammoth", lambda: (_text_from_mammoth(path), None)),
            ("markitdown", lambda: (_text_from_markitdown(path), None)),
        ])
    if suffix in _MARKITDOWN_SUFFIXES:
        return _try_text_extractors([("markitdown", lambda: (_text_from_markitdown(path), None))])
    return _try_text_extractors([("markitdown", lambda: (_text_from_markitdown(path), None))])


def _extract_document_text(path: Path) -> tuple[str, int | None]:
    text, pages, _backend = _extract_document_content(path)
    return text, pages


def _user_facing_text(label: str, mode: str, summary: str, bullets: list[str], text: str) -> str:
    title = label or "Paylaşılan metin"
    if mode == "summary":
        return f"{title}\n{summary}"
    if mode == "bullets":
        if not bullets:
            return f"{title}\nMetin çıkarıldı ama maddelendirilecek içerik bulunamadı."
        return f"{title}\n" + "\n".join(f"• {item}" for item in bullets)
    preview = summarize_text(text, max_chars=640)
    return f"{title}\n{preview}"


def document_read(
    path: str = "",
    mode: str = "read",
    text: str = "",
    _selectedPaths: list[str] | None = None,
) -> dict[str, Any]:
    normalized_mode = ensure_mode(mode)
    source_label = "Paylaşılan metin"
    content_type = "text/plain"
    source_path = ""

    if str(text or "").strip():
        extracted_text = str(text or "").strip()
        pages = None
        backend = "provided_text"
    else:
        resolved = ensure_allowed_path(
            path,
            allowed_suffixes=_ALLOWED_SUFFIXES,
            selected_paths=_selectedPaths,
            root_resolver=_workspace_root,
        )
        source_label = resolved.name
        content_type = content_type_for(resolved)
        source_path = str(resolved)
        extracted_text, pages, backend = _extract_document_content(resolved)

    trimmed_text = preview_text(extracted_text)
    if not trimmed_text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "Belgede okunabilir metin bulunamadı.")

    summary = summarize_text(trimmed_text, max_chars=320)
    bullets = bulletize_text(trimmed_text)
    return {
        "text": _user_facing_text(source_label, normalized_mode, summary, bullets, trimmed_text),
        "result": {
            "kind": "document_read",
            "sourcePath": source_path,
            "sourceKind": "text" if source_path == "" else "file",
            "contentType": content_type,
            "pages": pages,
            "backend": backend,
            "mode": normalized_mode,
            "text": trimmed_text,
            "summary": summary,
            "bullets": bullets,
        },
        "artifacts": [],
    }
