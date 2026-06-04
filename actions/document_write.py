from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import bulletize_text, ensure_allowed_path, summarize_text
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from actions.document_read import _ALLOWED_SUFFIXES as _READ_ALLOWED_SUFFIXES
from actions.document_read import _extract_document_text
from runtime.capability_registry import SafeCapabilityError


def _workspace_root() -> Path:
    from actions._read_only_common import workspace_root

    return workspace_root()


def _resolve_source_text(source_path: str, source_context: str, prompt: str) -> tuple[str, str]:
    if str(source_context or "").strip():
        text = str(source_context or "").strip()
        return text, normalize_source_context(text)
    if str(source_path or "").strip():
        resolved = ensure_allowed_path(
            source_path,
            allowed_suffixes=_READ_ALLOWED_SUFFIXES,
            root_resolver=_workspace_root,
        )
        extracted, _ = _extract_document_text(resolved)
        text = str(extracted or "").strip()
        if not text:
            raise SafeCapabilityError("EMPTY_DOCUMENT", "Kaynak belgede yazılabilir içerik bulunamadı.")
        return text, resolved.name
    text = str(prompt or "").strip()
    if not text:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Belge oluşturmak için bir içerik veya hedef gerekli.")
    return text, normalize_source_context(text)


def document_write(
    prompt: str = "",
    output_path: str = "",
    title: str = "",
    sections: list[dict[str, Any]] | None = None,
    source_path: str = "",
    source_context: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    from docx import Document  # type: ignore[reportMissingImports]

    resolved_output = ensure_allowed_output_path(
        output_path,
        extension=".docx",
        overwrite=overwrite,
        hint=title or prompt or source_path or "elyan-document",
        root_resolver=_workspace_root,
    )
    body_text, source_summary = _resolve_source_text(source_path, source_context, prompt)

    document = Document()
    heading = str(title or resolved_output.stem).strip() or "Elyan Document"
    document.add_heading(heading, level=0)

    normalized_sections = [item for item in (sections or []) if isinstance(item, dict)]
    if normalized_sections:
        for section in normalized_sections:
            section_title = str(section.get("heading", "") or section.get("title", "") or "").strip()
            section_body = str(section.get("body", "") or section.get("text", "") or "").strip()
            if section_title:
                document.add_heading(section_title, level=1)
            if section_body:
                document.add_paragraph(section_body)
    else:
        for block in [part.strip() for part in body_text.split("\n\n") if part.strip()]:
            document.add_paragraph(block)

    document.save(str(resolved_output))
    summary = summarize_text(body_text, max_chars=260)
    return {
        "text": f"DOCX oluşturuldu: {resolved_output.name}",
        "result": {
            "kind": "document_write",
            "sourceContext": source_summary,
            "sourcePath": str(source_path or "").strip(),
            "outputPath": str(resolved_output),
            "contentType": artifact_payload(resolved_output)["contentType"],
            "created": True,
            "title": heading,
            "summary": summary,
            "bullets": bulletize_text(body_text),
        },
        "artifacts": [artifact_payload(resolved_output)],
    }
