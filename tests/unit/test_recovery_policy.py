from __future__ import annotations

from core.recovery_policy import select_recovery_strategy


def test_recovery_policy_policy_block_is_fail_fast():
    strategy = select_recovery_strategy(
        failure_class="policy_block",
        action="run_safe_command",
        reason="Security policy blocked this action.",
        params={"command": "echo ok"},
        result={},
    )
    assert strategy.get("kind") == "fail_fast"
    assert strategy.get("stop_retry") is True


def test_recovery_policy_state_mismatch_refocuses_target_app():
    strategy = select_recovery_strategy(
        failure_class="state_mismatch",
        action="key_combo",
        reason="hedef uygulama doğrulanamadı",
        params={"combo": "cmd+t", "target_app": "Safari"},
        result={"frontmost_app": "Finder"},
    )
    assert strategy.get("kind") == "refocus_app"
    assert strategy.get("stop_retry") is False
    assert strategy.get("focus_app") == "Safari"


def test_recovery_policy_tool_failure_normalizes_terminal_command():
    strategy = select_recovery_strategy(
        failure_class="tool_failure",
        action="run_safe_command",
        reason="command failed",
        params={"command": "cd desktop komutu"},
        result={},
    )
    assert strategy.get("kind") == "patch_params"
    patch = strategy.get("params_patch") or {}
    assert patch.get("command") == "cd desktop"


def test_recovery_policy_planning_failure_replays_taskspec_artifact():
    strategy = select_recovery_strategy(
        failure_class="planning_failure",
        action="write_file",
        reason="document:missing_artifact, criteria:artifact_file_not_empty",
        params={},
        result={
            "task_spec": {"steps": [{"action": "write_file", "params": {"path": "/tmp/report.md", "content": "x"}}]},
            "failed": ["document:missing_artifact", "criteria:artifact_file_not_empty"],
        },
    )
    assert strategy.get("kind") == "replay_taskspec_artifact"
    assert strategy.get("stop_retry") is False


def test_recovery_policy_planning_failure_builds_quality_gate_plan():
    strategy = select_recovery_strategy(
        failure_class="planning_failure",
        action="write_file",
        reason="code:lint, code:smoke",
        params={},
        result={
            "code_gate": {"failed": ["lint", "smoke"]},
            "quality_gate_commands": ["ruff check .", "python -m pytest -q"],
        },
    )
    assert strategy.get("kind") == "quality_gate_plan"
    assert strategy.get("stop_retry") is False


def test_recovery_policy_planning_failure_builds_research_revision_plan():
    strategy = select_recovery_strategy(
        failure_class="planning_failure",
        action="research_document_delivery",
        reason="research:sources, research:claim_mapping",
        params={},
        result={
            "research_gate": {"failed": ["sources", "claim_mapping"]},
            "research_repair_steps": ["En az 3 güvenilir kaynak ekle", "Ana iddiaları kaynaklarla eşle"],
        },
    )
    assert strategy.get("kind") == "research_revision_plan"
    assert strategy.get("stop_retry") is False
