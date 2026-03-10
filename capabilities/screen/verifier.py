from __future__ import annotations

from typing import Any

from core.pipeline_upgrade.executor import collect_paths_from_tool_results


def verify_screen_runtime(ctx: Any) -> dict[str, Any]:
    tool_results = [r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)]
    screenshots = collect_paths_from_tool_results(tool_results)
    summary_present = False
    active_window_identified = False
    vision_or_ocr_present = False

    for row in tool_results:
        payloads = [row]
        for key in ("result", "raw"):
            nested = row.get(key)
            if isinstance(nested, dict):
                payloads.append(nested)
        for payload in payloads:
            ui_map = payload.get("ui_map") if isinstance(payload.get("ui_map"), dict) else {}
            if str(payload.get("summary") or payload.get("analysis") or payload.get("message") or "").strip():
                summary_present = True
            if str(payload.get("ocr") or "").strip() or payload.get("objects"):
                vision_or_ocr_present = True
            if str(ui_map.get("frontmost_app") or "").strip():
                active_window_identified = True
            observations = payload.get("observations")
            if isinstance(observations, list):
                for item in observations:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("summary") or "").strip():
                        summary_present = True
                    obs_ui_map = item.get("ui_map") if isinstance(item.get("ui_map"), dict) else {}
                    if str(obs_ui_map.get("frontmost_app") or "").strip():
                        active_window_identified = True

    checks = [
        {"check": "screenshot_created", "passed": bool(screenshots), "count": len(screenshots)},
        {"check": "summary_present", "passed": summary_present},
        {"check": "active_window_identified", "passed": active_window_identified},
        {"check": "vision_or_ocr_result_present", "passed": vision_or_ocr_present},
    ]
    failed = [item["check"] for item in checks if item["passed"] is False]
    return {
        "capability": "screen",
        "ok": len(failed) == 0,
        "checks": checks,
        "failed": failed,
        "screenshots": screenshots,
    }

