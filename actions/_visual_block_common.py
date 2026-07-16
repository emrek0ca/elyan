from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import ensure_allowed_path


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def validate_visual_block_paths(
    blocks: list[dict[str, Any]],
    *,
    selected_paths: list[str] | None = None,
    root_resolver,
) -> list[dict[str, Any]]:
    """Resolve model-provided image paths through the task-scoped file gate."""
    validated: list[dict[str, Any]] = []
    for block in blocks:
        current = dict(block)
        if str(current.get("kind", "") or "").strip().lower() == "image":
            current["path"] = str(
                ensure_allowed_path(
                    str(current.get("path", "") or ""),
                    allowed_suffixes=_IMAGE_SUFFIXES,
                    selected_paths=selected_paths,
                    root_resolver=root_resolver,
                )
            )
        validated.append(current)
    return validated


def _clean_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _clean_int(value: Any, *, default: int = 0, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        result = int(round(float(value)))
    except Exception:
        result = default
    result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _normalize_text_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in [chunk.strip() for chunk in str(text or "").split("\n\n") if chunk.strip()]:
        blocks.append({"kind": "text", "text": part})
    return blocks


def _unique_headers(rows: list[dict[str, Any]]) -> list[str]:
    headers: list[str] = []
    for row in rows:
        for key in row.keys():
            candidate = _clean_text(key, limit=80)
            if candidate and candidate not in headers:
                headers.append(candidate)
    return headers


def _normalize_table_block(block: dict[str, Any]) -> dict[str, Any] | None:
    raw_headers = block.get("headers") or block.get("columns") or []
    raw_rows = block.get("rows") or block.get("data") or block.get("items") or []

    headers = [_clean_text(item, limit=80) for item in raw_headers if _clean_text(item, limit=80)]
    rows: list[list[str]] = []

    if isinstance(raw_rows, list):
        dict_rows = [item for item in raw_rows if isinstance(item, dict)]
        if dict_rows:
            if not headers:
                headers = _unique_headers(dict_rows)
            for row in dict_rows:
                rows.append([_clean_text(row.get(header, row.get(header.lower(), ""))) for header in headers])
        else:
            for row in raw_rows:
                if isinstance(row, (list, tuple)):
                    rows.append([_clean_text(cell) for cell in row])
                elif row is not None:
                    rows.append([_clean_text(row)])

    if not rows:
        return None

    if not headers:
        headers = [f"Kolon {index + 1}" for index in range(max(len(row) for row in rows))]

    normalized_rows: list[list[str]] = []
    width = len(headers)
    for row in rows:
        current = list(row[:width])
        if len(current) < width:
            current.extend([""] * (width - len(current)))
        normalized_rows.append(current)

    return {
        "kind": "table",
        "title": _clean_text(block.get("title", "") or block.get("caption", ""), limit=120),
        "headers": headers,
        "rows": normalized_rows,
    }


def _normalize_image_block(block: dict[str, Any]) -> dict[str, Any] | None:
    path = _clean_text(
        block.get("path", "")
        or block.get("sourcePath", "")
        or block.get("source_path", "")
        or block.get("filePath", ""),
        limit=1024,
    )
    if not path:
        return None
    return {
        "kind": "image",
        "path": path,
        "alt": _clean_text(block.get("alt", "") or block.get("title", "") or "", limit=180),
        "width": _clean_int(block.get("width"), default=0, minimum=0),
        "height": _clean_int(block.get("height"), default=0, minimum=0),
        "fit": _clean_text(block.get("fit", "") or "contain", limit=24) or "contain",
    }


def _clean_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _listify_chart_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for candidate in (
            value.get("values"),
            value.get("data"),
            value.get("labels"),
            value.get("categories"),
            value.get("x"),
            value.get("y"),
        ):
            if isinstance(candidate, list):
                return candidate
    return []


def _normalize_chart_block(block: dict[str, Any]) -> dict[str, Any] | None:
    chart_type = _clean_text(block.get("chartType", "") or block.get("chart_type", "") or "bar", limit=24).lower()
    if chart_type not in {"bar", "line", "scatter", "histogram"}:
        chart_type = "bar"

    raw_labels = block.get("labels") or block.get("categories") or block.get("xValues") or block.get("x_values") or block.get("x") or []
    raw_values = block.get("values") or block.get("yValues") or block.get("y_values") or block.get("y") or []
    labels = [_clean_text(item, limit=120) for item in _listify_chart_value(raw_labels) if _clean_text(item, limit=120)]
    values = [_clean_float(item) for item in _listify_chart_value(raw_values)]
    source_path = _clean_text(block.get("sourcePath", "") or block.get("source_path", "") or block.get("path", ""), limit=1024)
    x_label = _clean_text(block.get("xLabel", "") or block.get("x_label", "") or "", limit=80)
    y_label = _clean_text(block.get("yLabel", "") or block.get("y_label", "") or "", limit=80)

    if labels and values:
        width = min(len(labels), len(values))
        labels = labels[:width]
        values = values[:width]
    elif labels and not values and chart_type != "histogram":
        values = [float(index + 1) for index in range(len(labels))]
    elif values and not labels and chart_type != "histogram":
        labels = [str(index + 1) for index in range(len(values))]

    if not source_path and not labels and not values:
        return None
    if chart_type == "histogram" and not values and not source_path:
        return None

    return {
        "kind": "chart",
        "title": _clean_text(block.get("title", "") or block.get("caption", ""), limit=120),
        "chartType": chart_type,
        "labels": labels,
        "values": values,
        "sourcePath": source_path,
        "xLabel": x_label,
        "yLabel": y_label,
        "xColumn": _clean_text(block.get("xColumn", "") or block.get("x_column", ""), limit=80),
        "yColumn": _clean_text(block.get("yColumn", "") or block.get("y_column", ""), limit=80),
        "width": _clean_int(block.get("width"), default=0, minimum=0),
        "height": _clean_int(block.get("height"), default=0, minimum=0),
    }


def render_chart_block_to_png(block: dict[str, Any], output_path: Path) -> Path:
    from actions import _data_common
    from actions.chart_generate import _ensure_chart_type, _render_chart

    chart_type = _ensure_chart_type(block.get("chartType", "") or block.get("chart_type", "") or "bar")
    source_path = str(block.get("sourcePath", "") or block.get("source_path", "") or "").strip()
    labels = [str(item) for item in (block.get("labels", []) or []) if str(item).strip()]
    values = [_clean_float(item) for item in (block.get("values", []) or [])]
    title = _clean_text(block.get("title", "") or block.get("caption", ""), limit=120)
    x_column = str(block.get("xColumn", "") or block.get("x_column", "") or "").strip()
    y_column = str(block.get("yColumn", "") or block.get("y_column", "") or "").strip()

    frame = None
    if source_path:
        resolved = _data_common.resolve_data_path(source_path, [])
        frame = _data_common.load_dataframe(resolved)
        if int(getattr(frame, "shape", (0, 0))[0] or 0) <= 0:
            raise ValueError("Grafik üretmek için veri kümesi boş.")
        x_column, y_column = _data_common.infer_chart_columns(
            frame,
            chart_type=chart_type,
            x_column=x_column,
            y_column=y_column,
        )
    else:
        if chart_type == "histogram":
            if not values:
                raise ValueError("Grafik bloğu için veri bulunamadı.")
            import pandas as pd  # type: ignore[reportMissingImports]

            column_name = x_column or "value"
            frame = pd.DataFrame({column_name: values})
            x_column = column_name
            y_column = column_name
        else:
            if not labels and not values:
                raise ValueError("Grafik bloğu için veri bulunamadı.")
            if labels and not values:
                values = [float(index + 1) for index in range(len(labels))]
            if values and not labels:
                labels = [str(index + 1) for index in range(len(values))]
            width = min(len(labels), len(values))
            labels = labels[:width]
            values = values[:width]
            import pandas as pd  # type: ignore[reportMissingImports]

            x_column = x_column or "label"
            y_column = y_column or "value"
            frame = pd.DataFrame({x_column: labels, y_column: values})

    if frame is None:
        raise ValueError("Grafik üretmek için veri bulunamadı.")

    _render_chart(
        frame,
        chart_type=chart_type,
        x_column=x_column or "label",
        y_column=y_column or "value",
        title=title,
        output_path=output_path,
    )
    return output_path


def _normalize_text_block(block: dict[str, Any]) -> dict[str, Any] | None:
    text = _clean_text(
        block.get("text", "")
        or block.get("body", "")
        or block.get("value", "")
        or block.get("content", ""),
        limit=8000,
    )
    if not text:
        return None
    level = _clean_int(block.get("level"), default=0, minimum=0, maximum=6)
    if str(block.get("kind", "") or "").strip().lower() in {"title", "heading"} and level <= 0:
        level = 1
    return {
        "kind": "text",
        "text": text,
        "level": level,
    }


def _normalize_spacer_block(block: dict[str, Any]) -> dict[str, Any] | None:
    height = _clean_int(block.get("height") or block.get("size") or 16, default=16, minimum=0, maximum=1200)
    if height <= 0:
        return None
    return {
        "kind": "spacer",
        "height": height,
    }


def normalize_visual_blocks(
    blocks: Any,
    *,
    fallback_text: str = "",
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    source = blocks
    if source is None:
        source = []

    if isinstance(source, dict):
        source = [source]
    elif isinstance(source, (str, int, float)) and str(source).strip():
        source = [str(source)]

    if isinstance(source, list):
        for item in source:
            if isinstance(item, str):
                normalized.extend(_normalize_text_blocks(item))
                continue
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "") or item.get("type", "") or "").strip().lower()
            if not kind:
                if any(key in item for key in ("headers", "rows", "data", "columns")):
                    kind = "table"
                elif any(key in item for key in ("path", "sourcePath", "source_path", "filePath")):
                    kind = "image"
                else:
                    kind = "text"
            if kind in {"text", "paragraph", "heading", "title"}:
                text_block = _normalize_text_block(item)
                if text_block is not None:
                    normalized.append(text_block)
                continue
            if kind in {"chart", "graph", "plot"} or any(
                key in item for key in ("chartType", "chart_type", "labels", "values", "xLabel", "yLabel", "xColumn", "yColumn")
            ):
                chart_block = _normalize_chart_block(item)
                if chart_block is not None:
                    normalized.append(chart_block)
                continue
            if kind == "table":
                table_block = _normalize_table_block(item)
                if table_block is not None:
                    normalized.append(table_block)
                continue
            if kind == "image":
                image_block = _normalize_image_block(item)
                if image_block is not None:
                    normalized.append(image_block)
                continue
            if kind == "spacer":
                spacer_block = _normalize_spacer_block(item)
                if spacer_block is not None:
                    normalized.append(spacer_block)
                continue
            if kind in {"page_break", "pagebreak"}:
                normalized.append({"kind": "page_break"})
                continue
            text_block = _normalize_text_block(item)
            if text_block is not None:
                normalized.append(text_block)

    if normalized:
        return normalized

    if fallback_text.strip():
        return _normalize_text_blocks(fallback_text)

    return []


def split_text_blocks(*values: Any) -> list[dict[str, Any]]:
    pieces: list[dict[str, Any]] = []
    for value in values:
        text = _clean_text(value, limit=8000)
        if text:
            pieces.extend(_normalize_text_blocks(text))
    return pieces


def table_column_count(headers: list[str], rows: list[list[str]]) -> int:
    if headers:
        return len(headers)
    return max([len(row) for row in rows] or [0])


def table_ensure_width(headers: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    width = table_column_count(headers, rows)
    if width <= 0:
        return headers, rows
    normalized_headers = list(headers)
    if len(normalized_headers) < width:
        normalized_headers.extend([f"Kolon {index + 1}" for index in range(len(normalized_headers), width)])
    normalized_rows: list[list[str]] = []
    for row in rows:
        current = list(row[:width])
        if len(current) < width:
            current.extend([""] * (width - len(current)))
        normalized_rows.append(current)
    return normalized_headers, normalized_rows
