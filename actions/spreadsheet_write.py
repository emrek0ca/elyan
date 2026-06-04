from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import bulletize_text, summarize_text
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from runtime.capability_registry import SafeCapabilityError


def _workspace_root() -> Path:
    from actions._read_only_common import workspace_root

    return workspace_root()


def _normalize_rows(rows: Any) -> list[list[str]]:
    normalized: list[list[str]] = []
    if not isinstance(rows, list):
        return normalized
    for row in rows:
        if isinstance(row, dict):
            normalized.append([str(value) for value in row.values()])
        elif isinstance(row, (list, tuple)):
            normalized.append([str(value) for value in row])
        elif row is not None:
            normalized.append([str(row)])
    return normalized


def spreadsheet_write(
    prompt: str = "",
    output_path: str = "",
    title: str = "",
    columns: list[str] | None = None,
    rows: list[Any] | None = None,
    source_context: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    from openpyxl import Workbook  # type: ignore[reportMissingImports]

    resolved_output = ensure_allowed_output_path(
        output_path,
        extension=".xlsx",
        overwrite=overwrite,
        hint=title or prompt or "elyan-sheet",
        root_resolver=_workspace_root,
    )
    seed_text = str(source_context or prompt or "").strip()
    if not seed_text and not rows:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Çalışma sayfası oluşturmak için içerik veya satır verisi gerekli.")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (str(title or "Elyan Sheet").strip() or "Elyan Sheet")[:31]

    normalized_columns = [str(item) for item in (columns or []) if str(item).strip()]
    normalized_rows = _normalize_rows(rows)
    if normalized_columns:
        sheet.append(normalized_columns)
    if normalized_rows:
        for row in normalized_rows:
            sheet.append(row)
    else:
        header = normalized_columns or ["Content"]
        if not normalized_columns:
            sheet.append(header)
        for bullet in bulletize_text(seed_text, limit=24):
            sheet.append([bullet])

    workbook.save(str(resolved_output))
    return {
        "text": f"XLSX oluşturuldu: {resolved_output.name}",
        "result": {
            "kind": "spreadsheet_write",
            "sourceContext": normalize_source_context(seed_text or "structured_rows"),
            "outputPath": str(resolved_output),
            "contentType": artifact_payload(resolved_output)["contentType"],
            "created": True,
            "title": sheet.title,
            "summary": summarize_text(seed_text or "Spreadsheet created.", max_chars=260),
        },
        "artifacts": [artifact_payload(resolved_output)],
    }
