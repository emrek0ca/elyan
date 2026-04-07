from __future__ import annotations

from core.personalization.policy_learning import LearningSignal, PolicyLearningStore


def test_q_value_moves_with_success_and_failure(tmp_path):
    store = PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3", alpha=0.5, explore_c=0.2)
    user_id = "u1"
    task_type = "file_operation"
    action = "write_file"

    store.record_signal(
        LearningSignal(
            user_id=user_id,
            task_type=task_type,
            action=action,
            agent_id="agent_a",
            outcome="success",
            latency_ms=120,
            source="implicit",
        )
    )
    q_after_success = store.get_action_rankings_ucb(
        user_id, task_type, [action], explore_c=0.0
    )[0]["q_value"]

    store.record_signal(
        LearningSignal(
            user_id=user_id,
            task_type=task_type,
            action=action,
            agent_id="agent_a",
            outcome="failed",
            latency_ms=6000,
            retry_count=2,
            source="implicit",
        )
    )
    q_after_failure = store.get_action_rankings_ucb(
        user_id, task_type, [action], explore_c=0.0
    )[0]["q_value"]

    assert q_after_success > 0.0
    assert q_after_failure < q_after_success


def test_ucb_selects_best_action_when_explore_is_zero(tmp_path):
    store = PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3", alpha=0.3, explore_c=0.2)
    user_id = "u2"
    task_type = "api_call"

    for _ in range(3):
        store.record_signal(
            LearningSignal(
                user_id=user_id,
                task_type=task_type,
                action="tool_fast",
                agent_id="agent_fast",
                outcome="success",
                latency_ms=80,
                source="implicit",
            )
        )
    for _ in range(2):
        store.record_signal(
            LearningSignal(
                user_id=user_id,
                task_type=task_type,
                action="tool_slow",
                agent_id="agent_slow",
                outcome="failed",
                latency_ms=8000,
                source="implicit",
            )
        )

    selected = store.select_action_ucb(
        user_id=user_id,
        task_type=task_type,
        actions=["tool_fast", "tool_slow"],
        explore_c=0.0,
    )
    assert selected == "tool_fast"


def test_user_learning_data_isolated(tmp_path):
    store = PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3", alpha=0.4, explore_c=0.2)
    task_type = "general"
    action = "chat"

    store.record_signal(
        LearningSignal(
            user_id="user_a",
            task_type=task_type,
            action=action,
            agent_id="agent",
            outcome="success",
            latency_ms=50,
            source="implicit",
        )
    )
    store.record_signal(
        LearningSignal(
            user_id="user_b",
            task_type=task_type,
            action=action,
            agent_id="agent",
            outcome="failed",
            latency_ms=9000,
            source="implicit",
        )
    )

    score_a = store.get_learning_score("user_a")
    score_b = store.get_learning_score("user_b")
    assert score_a > score_b
