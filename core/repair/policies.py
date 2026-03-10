from __future__ import annotations

from dataclasses import dataclass

from core.contracts.failure_taxonomy import FailureCode, RETRYABLE_FAILURE_CODES


@dataclass(frozen=True)
class RepairPolicy:
    code: str
    strategy: str
    retry_budget: int
    verifier: str
    retryable: bool
    description: str = ""


_POLICIES: dict[str, RepairPolicy] = {
    FailureCode.INTENT_PARAM_MISSING.value: RepairPolicy(
        code=FailureCode.INTENT_PARAM_MISSING.value,
        strategy="derive_or_request_missing_params",
        retry_budget=1,
        verifier="required_params_present",
        retryable=True,
        description="Derive missing parameters from current context or ask once.",
    ),
    FailureCode.ARTIFACT_MISSING.value: RepairPolicy(
        code=FailureCode.ARTIFACT_MISSING.value,
        strategy="rerun_artifact_producer",
        retry_budget=2,
        verifier="artifact_manifest_complete",
        retryable=True,
        description="Re-run only the step responsible for the missing artifact.",
    ),
    FailureCode.SCREEN_SUMMARY_MISSING.value: RepairPolicy(
        code=FailureCode.SCREEN_SUMMARY_MISSING.value,
        strategy="synthesize_screen_summary",
        retry_budget=1,
        verifier="screen_summary_present",
        retryable=True,
        description="Regenerate summary from OCR and accessibility state.",
    ),
    FailureCode.BUILD_FAILED.value: RepairPolicy(
        code=FailureCode.BUILD_FAILED.value,
        strategy="patch_and_rerun_build",
        retry_budget=2,
        verifier="build_gates_passed",
        retryable=True,
        description="Patch implicated files and rerun build gates.",
    ),
    FailureCode.EMPTY_FILE_OUTPUT.value: RepairPolicy(
        code=FailureCode.EMPTY_FILE_OUTPUT.value,
        strategy="regenerate_non_empty_file",
        retry_budget=2,
        verifier="file_non_empty",
        retryable=True,
        description="Regenerate the requested file until it passes content gates.",
    ),
    FailureCode.DELIVERY_UNSUPPORTED_CHANNEL.value: RepairPolicy(
        code=FailureCode.DELIVERY_UNSUPPORTED_CHANNEL.value,
        strategy="repackage_for_supported_channel",
        retry_budget=1,
        verifier="delivery_contract_valid",
        retryable=True,
        description="Repackage output into a channel-supported mode.",
    ),
    FailureCode.UI_TARGET_NOT_FOUND.value: RepairPolicy(
        code=FailureCode.UI_TARGET_NOT_FOUND.value,
        strategy="refresh_ui_state_and_retry",
        retry_budget=2,
        verifier="ui_target_resolved",
        retryable=True,
        description="Refresh UI state from accessibility, vision, and OCR before retrying.",
    ),
    FailureCode.NO_VISUAL_CHANGE.value: RepairPolicy(
        code=FailureCode.NO_VISUAL_CHANGE.value,
        strategy="reobserve_then_react",
        retry_budget=2,
        verifier="visual_change_detected",
        retryable=True,
        description="Capture a fresh before/after observation and retry one action.",
    ),
    FailureCode.TOOL_CONTRACT_VIOLATION.value: RepairPolicy(
        code=FailureCode.TOOL_CONTRACT_VIOLATION.value,
        strategy="fail_fast_contract_violation",
        retry_budget=0,
        verifier="tool_contract_valid",
        retryable=False,
        description="Legacy tool output was structurally invalid.",
    ),
    FailureCode.MEMORY_PRESSURE.value: RepairPolicy(
        code=FailureCode.MEMORY_PRESSURE.value,
        strategy="compact_context_then_retry",
        retry_budget=1,
        verifier="memory_below_threshold",
        retryable=True,
        description="Trim context and downscale artifacts before retrying.",
    ),
    FailureCode.TIME_BUDGET_EXCEEDED.value: RepairPolicy(
        code=FailureCode.TIME_BUDGET_EXCEEDED.value,
        strategy="fail_on_budget_exhaustion",
        retry_budget=0,
        verifier="time_budget_available",
        retryable=False,
        description="The action exhausted its time budget and should stop.",
    ),
}


DEFAULT_REPAIR_POLICY = RepairPolicy(
    code="UNKNOWN_FAILURE",
    strategy="controlled_failure",
    retry_budget=0,
    verifier="manual_review",
    retryable=False,
    description="Fallback policy when no deterministic mapping exists.",
)


def get_repair_policy(code: str | FailureCode | None) -> RepairPolicy:
    raw = code.value if isinstance(code, FailureCode) else str(code or "").strip()
    return _POLICIES.get(raw, DEFAULT_REPAIR_POLICY)


def is_retryable_failure(code: str | FailureCode | None) -> bool:
    raw = code.value if isinstance(code, FailureCode) else str(code or "").strip()
    return raw in {item.value for item in RETRYABLE_FAILURE_CODES}


__all__ = ["DEFAULT_REPAIR_POLICY", "RepairPolicy", "get_repair_policy", "is_retryable_failure"]
