from __future__ import annotations

from core.contracts.failure_taxonomy import FailureCode
from core.failure_classification import FailureClass, classify_failure_class


def test_classify_failure_class_policy_block_from_reason():
    out = classify_failure_class(reason="Security policy blocked this action.")
    assert out == FailureClass.POLICY_BLOCK.value


def test_classify_failure_class_perception_from_failure_code():
    out = classify_failure_class(failed_codes=[FailureCode.UI_TARGET_NOT_FOUND.value])
    assert out == FailureClass.PERCEPTION_FAILURE.value


def test_classify_failure_class_state_mismatch_from_failure_code():
    out = classify_failure_class(failed_codes=[FailureCode.WRONG_APP_CONTEXT.value])
    assert out == FailureClass.STATE_MISMATCH.value


def test_classify_failure_class_planning_from_reason():
    out = classify_failure_class(reason="unknown_dependency:task_9")
    assert out == FailureClass.PLANNING_FAILURE.value


def test_classify_failure_class_tool_from_reason():
    out = classify_failure_class(reason="step_timeout>90.0s")
    assert out == FailureClass.TOOL_FAILURE.value
