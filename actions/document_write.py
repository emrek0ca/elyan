from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from actions._read_only_common import bulletize_text, ensure_allowed_path, summarize_text
from actions._visual_block_common import normalize_visual_blocks, render_chart_block_to_png, split_text_blocks, table_ensure_width
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from actions.document_read import _ALLOWED_SUFFIXES as _READ_ALLOWED_SUFFIXES
from actions.document_read import _extract_document_text
from runtime.capability_registry import SafeCapabilityError


def _workspace_root() -> Path:
    from actions._read_only_common import workspace_root

    return workspace_root()


def _chart_temp_path() -> Path:
    directory = Path(tempfile.gettempdir())
    directory.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f"elyan-doc-chart-{uuid.uuid4().hex[:8]}-", suffix=".png", dir=str(directory))
    os.close(fd)
    return Path(raw_path)


def _resolve_source_text(
    source_path: str,
    source_context: str,
    prompt: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, str]:
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
        if allow_empty:
            return "", normalize_source_context(source_context or prompt or "structured document")
        raise SafeCapabilityError("INVALID_ARGUMENT", "Belge oluşturmak için bir içerik veya hedef gerekli.")
    return text, normalize_source_context(text)


def _section_blocks(sections: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading", "") or section.get("title", "") or "").strip()
        body = str(section.get("body", "") or section.get("text", "") or "").strip()
        if heading:
            blocks.append({"kind": "text", "text": heading, "level": 1})
        if body:
            blocks.extend(split_text_blocks(body))
        nested_blocks = section.get("blocks", [])
        if isinstance(nested_blocks, list) and nested_blocks:
            blocks.extend(normalize_visual_blocks(nested_blocks, fallback_text=""))
    return blocks


def _add_table(document: Any, block: dict[str, Any]) -> None:
    headers, rows = table_ensure_width(
        [str(item) for item in (block.get("headers", []) or [])],
        [[str(cell) for cell in row] for row in (block.get("rows", []) or [])],
    )
    if not rows and not headers:
        return
    if str(block.get("title", "") or "").strip():
        document.add_paragraph(str(block.get("title")).strip())
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for index, header in enumerate(headers):
        header_cells[index].text = header
    for row in rows:
        new_row = table.add_row().cells
        for index, cell in enumerate(row):
            new_row[index].text = cell


def _add_image(document: Any, block: dict[str, Any]) -> None:
    from docx.shared import Inches  # type: ignore[reportMissingImports]

    path = Path(str(block.get("path", "") or "")).expanduser()
    if not path.exists():
        return
    picture_width = float(block.get("width", 0) or 0)
    picture_height = float(block.get("height", 0) or 0)
    if picture_width > 0:
        width = Inches(max(1.5, min(6.5, picture_width / 144.0)))
        document.add_picture(str(path), width=width)
    elif picture_height > 0:
        height = Inches(max(1.0, min(6.5, picture_height / 144.0)))
        document.add_picture(str(path), height=height)
    else:
        document.add_picture(str(path), width=Inches(5.5))


def _add_blocks(document: Any, blocks: list[dict[str, Any]], temp_paths: list[Path] | None = None) -> None:
    for block in blocks:
        kind = str(block.get("kind", "") or "").strip().lower()
        if kind == "text":
            text = str(block.get("text", "") or "").strip()
            if not text:
                continue
            level = int(block.get("level", 0) or 0)
            if level > 0:
                document.add_heading(text, level=min(level, 3))
            else:
                for paragraph in [part.strip() for part in text.split("\n\n") if part.strip()]:
                    document.add_paragraph(paragraph)
            continue
        if kind == "table":
            _add_table(document, block)
            continue
        if kind == "image":
            _add_image(document, block)
            continue
        if kind == "chart":
            chart_path = _chart_temp_path()
            try:
                render_chart_block_to_png(block, chart_path)
                if temp_paths is not None:
                    temp_paths.append(chart_path)
                _add_image(document, {"path": str(chart_path), "width": block.get("width", 0), "height": block.get("height", 0)})
            except Exception:
                try:
                    chart_path.unlink(missing_ok=True)
                except Exception:
                    pass
            continue
        if kind == "spacer":
            document.add_paragraph("")


def document_write(
    prompt: str = "",
    output_path: str = "",
    title: str = "",
    sections: list[dict[str, Any]] | None = None,
    blocks: list[dict[str, Any]] | None = None,
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
    body_text, source_summary = _resolve_source_text(
        source_path,
        source_context,
        prompt,
        allow_empty=bool((blocks or []) or (sections or [])),
    )

    document = Document()
    heading = str(title or resolved_output.stem).strip() or "Elyan Document"
    document.add_heading(heading, level=0)
    temp_paths: list[Path] = []

    try:
        normalized_blocks = normalize_visual_blocks(
            [*(blocks or []), *_section_blocks([item for item in (sections or []) if isinstance(item, dict)])],
            fallback_text=body_text,
        )
        _add_blocks(document, normalized_blocks, temp_paths=temp_paths)

        document.save(str(resolved_output))
    finally:
        for path in temp_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                continue
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
