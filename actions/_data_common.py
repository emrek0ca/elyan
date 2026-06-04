from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from actions._read_only_common import content_type_for, ensure_allowed_path, summarize_text, workspace_root
from runtime.capability_registry import SafeCapabilityError

DATA_SUFFIXES = {".csv", ".json"}
DATA_ANALYZE_MODES = {"summary", "profile", "preview"}
CHART_TYPES = {"bar", "line", "scatter", "histogram"}
_PREVIEW_LIMIT = 5
_TOP_VALUE_LIMIT = 3


def _workspace_root() -> Path:
    return workspace_root()


def _pandas_module() -> Any:
    import pandas as pd  # type: ignore[reportMissingImports]

    return pd


def resolve_data_path(path: str, selected_paths: list[str] | None = None) -> Path:
    return ensure_allowed_path(
        path,
        allowed_suffixes=DATA_SUFFIXES,
        selected_paths=selected_paths,
        root_resolver=_workspace_root,
    )


def ensure_mode(value: str, *, allowed: set[str], default: str) -> str:
    normalized = str(value or default).strip().lower() or default
    if normalized not in allowed:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz veri işleme modu.")
    return normalized


def _json_to_dataframe(payload: Any) -> Any:
    pd = _pandas_module()
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) for item in payload):
            return pd.DataFrame(payload)
        return pd.DataFrame({"value": payload})
    if isinstance(payload, dict):
        if payload and all(isinstance(value, list) for value in payload.values()):
            return pd.DataFrame(payload)
        return pd.json_normalize(payload)
    raise SafeCapabilityError("INVALID_ARGUMENT", "JSON içeriği tablo olarak okunamadı.")


def load_dataframe(path: Path) -> Any:
    pd = _pandas_module()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _json_to_dataframe(payload)
    raise SafeCapabilityError("UNSUPPORTED_FORMAT", "Bu veri türü desteklenmiyor.")


def frame_columns(frame: Any) -> list[str]:
    return [str(column) for column in list(getattr(frame, "columns", []))]


def select_columns(frame: Any, columns: list[str] | None) -> Any:
    if not columns:
        return frame
    requested = [str(item).strip() for item in columns if str(item).strip()]
    if not requested:
        return frame
    available = frame_columns(frame)
    missing = [item for item in requested if item not in available]
    if missing:
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            f"Eksik kolonlar: {', '.join(missing[:4])}",
        )
    return frame[requested]


def _safe_scalar(value: Any) -> Any:
    pd = _pandas_module()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def preview_rows(frame: Any, *, limit: int = _PREVIEW_LIMIT) -> list[dict[str, Any]]:
    if int(getattr(frame, "shape", (0, 0))[1] or 0) <= 0:
        return []
    rows: list[dict[str, Any]] = []
    sample = frame.head(limit)
    columns = frame_columns(sample)
    for row in sample.to_dict(orient="records"):
        payload: dict[str, Any] = {}
        for column in columns:
            payload[column] = _safe_scalar(row.get(column))
        rows.append(payload)
    return rows


def numeric_column_names(frame: Any) -> list[str]:
    pd = _pandas_module()
    names: list[str] = []
    for column in frame_columns(frame):
        try:
            if pd.api.types.is_numeric_dtype(frame[column]):
                names.append(column)
        except Exception:
            continue
    return names


def infer_chart_columns(
    frame: Any,
    *,
    chart_type: str,
    x_column: str = "",
    y_column: str = "",
) -> tuple[str, str]:
    columns = frame_columns(frame)
    if not columns:
        raise SafeCapabilityError("EMPTY_DATASET", "Grafik üretmek için veri bulunamadı.")

    numeric_columns = numeric_column_names(frame)
    requested_x = str(x_column or "").strip()
    requested_y = str(y_column or "").strip()

    if requested_x and requested_x not in columns:
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Kolon bulunamadı: {requested_x}")
    if requested_y and requested_y not in columns:
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Kolon bulunamadı: {requested_y}")

    if chart_type == "histogram":
        chosen_x = requested_x or requested_y or (numeric_columns[0] if numeric_columns else columns[0])
        if chosen_x not in columns:
            raise SafeCapabilityError("INVALID_ARGUMENT", "Histogram için geçerli kolon bulunamadı.")
        if numeric_columns and chosen_x not in numeric_columns:
            raise SafeCapabilityError("INVALID_ARGUMENT", "Histogram için sayısal bir kolon gerekli.")
        return chosen_x, ""

    chosen_x = requested_x
    if not chosen_x:
        chosen_x = next((column for column in columns if column not in numeric_columns), "")
        if not chosen_x:
            chosen_x = columns[0]

    chosen_y = requested_y
    if not chosen_y:
        chosen_y = next((column for column in numeric_columns if column != chosen_x), "")
        if not chosen_y and numeric_columns:
            chosen_y = numeric_columns[0]

    if chosen_x not in columns or chosen_y not in columns:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Grafik için x ve y kolonları gerekli.")
    if numeric_columns and chosen_y not in numeric_columns:
        raise SafeCapabilityError("INVALID_ARGUMENT", f"Y kolonu sayısal olmalı: {chosen_y}")
    return chosen_x, chosen_y


def content_type(path: Path) -> str:
    return content_type_for(path)


def dataframe_summary(frame: Any, *, path: Path) -> str:
    row_count, column_count = [int(item) for item in getattr(frame, "shape", (0, 0))]
    columns = frame_columns(frame)
    if not columns:
        return summarize_text(f"{path.name}: veri kümesi boş.", max_chars=320)
    return summarize_text(
        f"{path.name}: {row_count} satır, {column_count} kolon. Kolonlar: {', '.join(columns[:8])}",
        max_chars=320,
    )


def column_top_values(frame: Any, column: str) -> list[Any]:
    try:
        series = frame[column].dropna()
    except Exception:
        return []
    if getattr(series, "empty", False):
        return []
    values = series.astype(str).value_counts().head(_TOP_VALUE_LIMIT).index.tolist()
    return [str(item) for item in values]
