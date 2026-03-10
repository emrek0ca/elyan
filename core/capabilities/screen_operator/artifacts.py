from __future__ import annotations

from typing import Any


def collect_screen_artifacts(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    screenshots: list[str] = []
    summaries: list[str] = []
    ui_states: list[dict[str, Any]] = []
    action_logs: list[dict[str, Any]] = []
    frontmost_apps: list[str] = []

    def _append_screenshot(raw: Any) -> None:
        clean = str(raw or "").strip()
        if clean and clean not in screenshots:
            screenshots.append(clean)

    def _visit(payload: dict[str, Any]) -> None:
        summary = str(payload.get("summary") or payload.get("analysis") or payload.get("message") or "").strip()
        if summary:
            summaries.append(summary)
        ui_map = payload.get("ui_map") if isinstance(payload.get("ui_map"), dict) else {}
        if ui_map:
            ui_states.append(dict(ui_map))
            app = str(ui_map.get("frontmost_app") or "").strip()
            if app and app not in frontmost_apps:
                frontmost_apps.append(app)
        if isinstance(payload.get("path"), str):
            _append_screenshot(payload.get("path"))
        if isinstance(payload.get("final_screenshot"), str):
            _append_screenshot(payload.get("final_screenshot"))
        for key in ("screenshots", "artifacts"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        _append_screenshot(item)
                    elif isinstance(item, dict):
                        _append_screenshot(item.get("path"))
        observations = payload.get("observations")
        if isinstance(observations, list):
            for item in observations:
                if isinstance(item, dict):
                    _visit(item)
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        if control:
            action_logs.append(dict(control))
            _visit(control)
        iterations = payload.get("iterations") if isinstance(payload.get("iterations"), list) else []
        if iterations:
            action_logs.extend([dict(item) for item in iterations if isinstance(item, dict)])

    for row in tool_results or []:
        if isinstance(row, dict):
            _visit(row)
            nested = row.get("result") if isinstance(row.get("result"), dict) else None
            if isinstance(nested, dict):
                _visit(nested)
            raw = row.get("raw") if isinstance(row.get("raw"), dict) else None
            if isinstance(raw, dict):
                _visit(raw)

    return {
        "screenshots": screenshots,
        "summaries": summaries,
        "ui_states": ui_states,
        "action_logs": action_logs,
        "frontmost_apps": frontmost_apps,
    }
