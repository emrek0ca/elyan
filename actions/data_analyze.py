from __future__ import annotations

from pathlib import Path
from typing import Any

from actions import _data_common


def _column_summary(frame: Any, column: str) -> dict[str, Any]:
    pd = _data_common._pandas_module()
    series = frame[column]
    null_count = int(series.isna().sum())
    unique_count = int(series.nunique(dropna=True))
    payload: dict[str, Any] = {
        "name": column,
        "nullCount": null_count,
        "uniqueCount": unique_count,
    }
    if pd.api.types.is_numeric_dtype(series):
        numeric = series.dropna()
        payload.update(
            {
                "type": "numeric",
                "min": _data_common._safe_scalar(numeric.min()) if not numeric.empty else None,
                "max": _data_common._safe_scalar(numeric.max()) if not numeric.empty else None,
                "mean": _data_common._safe_scalar(numeric.mean()) if not numeric.empty else None,
            }
        )
    else:
        payload.update(
            {
                "type": "categorical",
                "topValues": _data_common.column_top_values(frame, column),
            }
        )
    return payload


def _analysis_summary(frame: Any, *, path: Path) -> tuple[str, list[dict[str, Any]]]:
    columns = _data_common.frame_columns(frame)
    entries = [_column_summary(frame, column) for column in columns[:8]]
    summary = _data_common.dataframe_summary(frame, path=path)
    return summary, entries


def _profile_summary(frame: Any, *, path: Path) -> tuple[str, list[dict[str, Any]]]:
    summary, entries = _analysis_summary(frame, path=path)
    numeric_count = sum(1 for item in entries if item.get("type") == "numeric")
    categorical_count = sum(1 for item in entries if item.get("type") == "categorical")
    profile_summary = (
        f"{summary} Sayısal kolon: {numeric_count}, kategorik kolon: {categorical_count}."
        if entries
        else summary
    )
    return profile_summary, entries


def _user_text(
    path: Path,
    *,
    mode: str,
    summary: str,
    preview_rows: list[dict[str, Any]],
    columns: list[str],
) -> str:
    if mode == "preview":
        if not preview_rows:
            return f"{path.name}\nÖnizleme için satır bulunamadı."
        lines = [
            ", ".join(f"{key}: {value}" for key, value in row.items())
            for row in preview_rows[:3]
        ]
        return f"{path.name}\n" + "\n".join(lines)
    if mode == "profile":
        return f"{path.name}\n{summary}"
    return f"{path.name}\n{summary}\nKolonlar: {', '.join(columns[:8])}"


def data_analyze(
    path: str,
    mode: str = "summary",
    columns: list[str] | None = None,
    _selectedPaths: list[str] | None = None,
) -> dict[str, Any]:
    resolved = _data_common.resolve_data_path(path, _selectedPaths)
    normalized_mode = _data_common.ensure_mode(
        mode,
        allowed=_data_common.DATA_ANALYZE_MODES,
        default="summary",
    )
    frame = _data_common.load_dataframe(resolved)
    frame = _data_common.select_columns(frame, columns)
    row_count, column_count = [int(item) for item in getattr(frame, "shape", (0, 0))]
    column_names = _data_common.frame_columns(frame)
    preview_rows = _data_common.preview_rows(frame)

    if normalized_mode == "profile":
        summary, profile = _profile_summary(frame, path=resolved)
    else:
        summary, profile = _analysis_summary(frame, path=resolved)

    return {
        "text": _user_text(
            resolved,
            mode=normalized_mode,
            summary=summary,
            preview_rows=preview_rows,
            columns=column_names,
        ),
        "result": {
            "kind": "data_analyze",
            "sourcePath": str(resolved),
            "contentType": _data_common.content_type(resolved),
            "mode": normalized_mode,
            "rowCount": row_count,
            "columnCount": column_count,
            "columns": column_names,
            "summary": summary,
            "previewRows": preview_rows,
            "profile": profile,
        },
        "artifacts": [],
    }
