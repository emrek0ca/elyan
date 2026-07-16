from __future__ import annotations

import time
import uuid
from pathlib import Path

from actions import _data_common
from actions._write_common import artifact_payload, ensure_allowed_output_path
from runtime import state_store
from runtime.capability_registry import SafeCapabilityError

_ARTIFACT_LIMIT = 24


def _artifact_dir() -> Path:
    return state_store.CONFIG_DIR / "artifacts"


def _chart_path(chart_type: str) -> Path:
    directory = _artifact_dir()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    name = f"elyan-chart-{chart_type}-{timestamp}-{uuid.uuid4().hex[:8]}.png"
    return directory / name


def _prune_artifacts() -> None:
    try:
        items = sorted(
            _artifact_dir().glob("elyan-chart-*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for path in items[_ARTIFACT_LIMIT:]:
        try:
            path.unlink()
        except OSError:
            continue


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt  # type: ignore[reportMissingImports]

    return plt


def _ensure_chart_type(value: str) -> str:
    normalized = str(value or "bar").strip().lower() or "bar"
    if normalized not in _data_common.CHART_TYPES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz grafik tipi.")
    return normalized


def _series(frame, column: str):
    return frame[column]


def _prepare_chart_frame(frame, *, chart_type: str, x_column: str, y_column: str):
    if chart_type == "histogram":
        return frame[[x_column]].dropna(subset=[x_column]).copy(), "none"
    selected = frame[[x_column, y_column]].dropna(subset=[x_column, y_column]).copy()
    if chart_type != "bar" or selected.empty or not bool(selected[x_column].duplicated().any()):
        return selected, "none"
    selected[y_column] = selected[y_column].astype(float)
    grouped = selected.groupby(x_column, sort=False, dropna=False, as_index=False)[y_column].sum()
    return grouped, "sum"


def _render_chart(
    frame,
    *,
    chart_type: str,
    x_column: str,
    y_column: str,
    title: str,
    output_path: Path,
) -> None:
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(7.5, 4.6), dpi=160)
    try:
        if chart_type == "histogram":
            values = _series(frame, x_column).dropna()
            if values.empty:
                raise SafeCapabilityError("EMPTY_DATASET", "Histogram için veri bulunamadı.")
            axis.hist(values, bins=min(16, max(4, len(values) // 2)))
            axis.set_xlabel(x_column)
            axis.set_ylabel("count")
        else:
            x_values = _series(frame, x_column)
            y_values = _series(frame, y_column)
            if chart_type == "bar":
                axis.bar(x_values.astype(str), y_values)
            elif chart_type == "line":
                axis.plot(x_values, y_values, marker="o")
            else:
                axis.scatter(x_values, y_values)
            axis.set_xlabel(x_column)
            axis.set_ylabel(y_column)
        if title.strip():
            axis.set_title(title.strip())
        axis.grid(alpha=0.18)
        figure.tight_layout()
        figure.savefig(output_path, format="png")
    finally:
        plt.close(figure)


def chart_generate(
    path: str,
    chartType: str = "bar",
    xColumn: str = "",
    yColumn: str = "",
    title: str = "",
    outputPath: str = "",
    _selectedPaths: list[str] | None = None,
) -> dict:
    resolved = _data_common.resolve_data_path(path, _selectedPaths)
    chart_type = _ensure_chart_type(chartType)
    frame = _data_common.load_dataframe(resolved)
    if int(getattr(frame, "shape", (0, 0))[0] or 0) <= 0:
        raise SafeCapabilityError("EMPTY_DATASET", "Grafik üretmek için veri kümesi boş.")
    x_column, y_column = _data_common.infer_chart_columns(
        frame,
        chart_type=chart_type,
        x_column=xColumn,
        y_column=yColumn,
    )
    render_frame, aggregation = _prepare_chart_frame(
        frame,
        chart_type=chart_type,
        x_column=x_column,
        y_column=y_column,
    )
    if str(outputPath or "").strip():
        output_path = ensure_allowed_output_path(
            outputPath,
            extension=".png",
            overwrite=False,
            hint=title or f"{resolved.stem}-{chart_type}",
            root_resolver=_data_common._workspace_root,
        )
    else:
        output_path = _chart_path(chart_type)
    _render_chart(
        render_frame,
        chart_type=chart_type,
        x_column=x_column,
        y_column=y_column,
        title=title,
        output_path=output_path,
    )
    if not str(outputPath or "").strip():
        _prune_artifacts()
    display_title = title.strip() or f"{Path(path).stem or resolved.stem} {chart_type}"
    summary = f"{resolved.name} verisinden {chart_type} grafik üretildi."
    return {
        "text": f"{summary}\n{output_path.name}",
        "result": {
            "kind": "chart_generate",
            "sourcePath": str(resolved),
            "contentType": _data_common.content_type(resolved),
            "chartType": chart_type,
            "xColumn": x_column,
            "yColumn": y_column,
            "aggregation": aggregation,
            "dataPointCount": int(getattr(render_frame, "shape", (0, 0))[0] or 0),
            "title": display_title,
            "artifactPath": str(output_path),
            "outputPath": str(output_path),
            "created": True,
            "summary": summary,
        },
        "artifacts": [artifact_payload(output_path)],
    }
