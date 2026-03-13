from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from core.contracts.failure_taxonomy import FailureCode


class FailureClass(str, Enum):
    PERCEPTION_FAILURE = "perception_failure"
    PLANNING_FAILURE = "planning_failure"
    TOOL_FAILURE = "tool_failure"
    STATE_MISMATCH = "state_mismatch"
    POLICY_BLOCK = "policy_block"
    UNKNOWN_FAILURE = "unknown_failure"


_PERCEPTION_CODES = {
    FailureCode.UI_TARGET_NOT_FOUND.value,
    FailureCode.SCREEN_SUMMARY_MISSING.value,
}

_PLANNING_CODES = {
    FailureCode.INTENT_PARAM_MISSING.value,
    FailureCode.ARTIFACT_MISSING.value,
    FailureCode.EMPTY_FILE_OUTPUT.value,
}

_TOOL_CODES = {
    FailureCode.TOOL_CONTRACT_VIOLATION.value,
    FailureCode.BUILD_FAILED.value,
    FailureCode.MEMORY_PRESSURE.value,
    FailureCode.TIME_BUDGET_EXCEEDED.value,
    FailureCode.DOM_UNAVAILABLE.value,
    FailureCode.NATIVE_DIALOG_REQUIRED.value,
    FailureCode.UNCONTROLLED_BROWSER_CHROME.value,
}

_STATE_CODES = {
    FailureCode.NO_VISUAL_CHANGE.value,
    FailureCode.WRONG_APP_CONTEXT.value,
    FailureCode.WRONG_WINDOW_CONTEXT.value,
    FailureCode.TEXT_NOT_VERIFIED.value,
    FailureCode.SUBMIT_NOT_VERIFIED.value,
    FailureCode.NAVIGATION_NOT_VERIFIED.value,
}


def _normalize_codes(error_code: str = "", failed_codes: Iterable[Any] | None = None) -> list[str]:
    out: list[str] = []
    seed = [error_code] + list(failed_codes or [])
    for item in seed:
        code = str(item or "").strip().upper()
        if not code:
            continue
        if code not in out:
            out.append(code)
    return out


def classify_failure_class(
    *,
    reason: str = "",
    error_code: str = "",
    failed_codes: Iterable[Any] | None = None,
    action: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """Classify runtime failure into one of deterministic recovery classes."""
    _ = action  # reserved for future action-aware rules
    data = payload if isinstance(payload, dict) else {}
    reason_low = str(reason or "").strip().lower()

    # Policy gate should always win.
    policy_markers = (
        "security policy blocked",
        "tool policy blocked",
        "approval_required",
        "approval required",
        "kullanıcı tarafından iptal",
        "user_aborted",
        "policy_block",
        "runtime_guard_block",
        "noninteractive",
    )
    if any(token in reason_low for token in policy_markers):
        return FailureClass.POLICY_BLOCK.value

    codes = _normalize_codes(
        error_code=error_code or str(data.get("error_code") or ""),
        failed_codes=failed_codes or data.get("failed_codes") or [],
    )

    if any(code in _STATE_CODES for code in codes):
        return FailureClass.STATE_MISMATCH.value
    if any(code in _PERCEPTION_CODES for code in codes):
        return FailureClass.PERCEPTION_FAILURE.value
    if any(code in _PLANNING_CODES for code in codes):
        return FailureClass.PLANNING_FAILURE.value
    if any(code in _TOOL_CODES for code in codes):
        return FailureClass.TOOL_FAILURE.value

    state_markers = (
        "wrong_app_context",
        "wrong_window_context",
        "frontmost_app",
        "hedef dışı uygulama",
        "hedef disi uygulama",
        "hedef uygulama doğrulanamad",
        "hedef uygulama dogrulanamad",
        "state mismatch",
        "no_visual_change",
    )
    if any(token in reason_low for token in state_markers):
        return FailureClass.STATE_MISMATCH.value

    perception_markers = (
        "target not found",
        "ui_target_not_found",
        "buton bulunamad",
        "element bulunamad",
        "ekranda bulunamad",
        "ocr",
        "vision",
    )
    if any(token in reason_low for token in perception_markers):
        return FailureClass.PERCEPTION_FAILURE.value

    planning_markers = (
        "unknown_dependency",
        "unsupported_action",
        "invalid_task_spec",
        "validation_failed",
        "no_executable_steps",
        "missing param",
        "missing required",
        "unresolved",
        "cyclic",
        "döngüsel",
        "dongusel",
    )
    if any(token in reason_low for token in planning_markers):
        return FailureClass.PLANNING_FAILURE.value

    tool_markers = (
        "timeout",
        "tool_execution_failed",
        "command failed",
        "contract violation",
        "stderr",
        "traceback",
        "exception",
        "not found",
        "path_not_found",
    )
    if any(token in reason_low for token in tool_markers):
        return FailureClass.TOOL_FAILURE.value

    return FailureClass.UNKNOWN_FAILURE.value


__all__ = ["FailureClass", "classify_failure_class"]
