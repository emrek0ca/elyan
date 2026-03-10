from __future__ import annotations

from typing import Any

from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult

from .artifacts import collect_screen_artifacts
from .schema import build_screen_operator_contract


_CONTROL_MODES = {"control", "inspect_and_control"}


def verify_screen_operator_runtime(ctx: Any) -> dict[str, Any]:
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    contract = build_screen_operator_contract(action=str(getattr(ctx, "action", "") or ""), params=params)
    artifacts = collect_screen_artifacts([r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)])

    screenshots = list(artifacts.get("screenshots") or [])
    summaries = list(artifacts.get("summaries") or [])
    ui_states = list(artifacts.get("ui_states") or [])
    action_logs = list(artifacts.get("action_logs") or [])
    frontmost_apps = list(artifacts.get("frontmost_apps") or [])
    mode = str(contract.get("mode") or "inspect")

    checks: list[VerificationCheck] = [
        VerificationCheck(code="screenshot_created", passed=bool(screenshots), details={"count": len(screenshots)}),
        VerificationCheck(code="summary_present", passed=bool(summaries), details={"count": len(summaries)}),
        VerificationCheck(code="ui_state_present", passed=bool(ui_states), details={"count": len(ui_states)}),
        VerificationCheck(code="active_window_identified", passed=bool(frontmost_apps), details={"frontmost_apps": frontmost_apps}),
    ]

    if mode in _CONTROL_MODES:
        visual_change = bool(len(screenshots) >= 2 or action_logs)
        checks.append(VerificationCheck(code="after_screenshot_present", passed=bool(len(screenshots) >= 2), details={"count": len(screenshots)}))
        checks.append(VerificationCheck(code="action_log_present", passed=bool(action_logs), details={"count": len(action_logs)}))
        checks.append(VerificationCheck(code="visual_change_observed", passed=visual_change, details={"count": len(screenshots)}))

    result = VerificationResult.from_checks(
        checks,
        summary="screen_operator capability runtime verification",
        evidence_refs=[{"type": "screenshots", "count": len(screenshots)}, {"type": "ui_states", "count": len(ui_states)}],
        metrics={"screenshot_count": len(screenshots), "ui_state_count": len(ui_states), "action_log_count": len(action_logs)},
        repairable=True,
    )

    failed_codes: list[str] = []
    for item in checks:
        if item.passed:
            continue
        if item.code == "summary_present":
            failed_codes.append(FailureCode.SCREEN_SUMMARY_MISSING.value)
        elif item.code in {"after_screenshot_present", "visual_change_observed"}:
            failed_codes.append(FailureCode.NO_VISUAL_CHANGE.value)
        elif item.code == "ui_state_present":
            failed_codes.append(FailureCode.UI_TARGET_NOT_FOUND.value)
        else:
            failed_codes.append(FailureCode.ARTIFACT_MISSING.value)

    payload = result.to_dict()
    payload.update(
        {
            "capability": "screen",
            "capability_id": "screen_operator",
            "mode": mode,
            "screenshots": screenshots,
            "ui_states": ui_states,
            "summaries": summaries,
            "action_logs": action_logs,
            "failed_codes": list(dict.fromkeys(failed_codes)),
        }
    )
    return payload
