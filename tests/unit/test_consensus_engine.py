from __future__ import annotations

from core import consensus_engine as consensus_module
from core.personalization.policy_learning import PolicyLearningStore


def _make_engine(tmp_path, monkeypatch):
    store = PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3")
    monkeypatch.setattr(consensus_module, "get_policy_learning_store", lambda: store)
    return consensus_module.ConsensusEngine()


def test_weighted_consensus_selects_highest_score(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch)
    decision = engine.resolve(
        task_id="task-1",
        user_id="u1",
        task_type="file_operation",
        proposals=[
            consensus_module.AgentProposal(
                agent_id="planner",
                action="write_file",
                confidence=0.95,
                risk="low",
                rationale="primary",
                role="planner",
            ),
            consensus_module.AgentProposal(
                agent_id="planner_alt",
                action="read_file",
                confidence=0.55,
                risk="low",
                rationale="alt",
                role="planner",
            ),
        ],
        veto_policy="require_approval",
        explore_exploit_level=0.05,
    )
    assert decision.selected_action == "write_file"
    assert decision.blocked is False
    assert decision.requires_approval is False


def test_security_veto_blocks_when_policy_is_block(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch)
    decision = engine.resolve(
        task_id="task-2",
        user_id="u1",
        task_type="general",
        proposals=[
            consensus_module.AgentProposal(
                agent_id="security_policy_guard",
                action="delete_file",
                confidence=1.0,
                risk="critical",
                rationale="high risk detected",
                role="security_policy",
            ),
            consensus_module.AgentProposal(
                agent_id="planner",
                action="delete_file",
                confidence=0.9,
                risk="high",
                rationale="requested",
                role="planner",
            ),
        ],
        veto_policy="block",
        explore_exploit_level=0.1,
    )
    assert decision.vetoed is True
    assert decision.blocked is True
    assert decision.requires_approval is False


def test_tie_break_is_deterministic_for_same_seed(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch)
    proposals = [
        consensus_module.AgentProposal(
            agent_id="a1",
            action="action_a",
            confidence=0.8,
            risk="low",
            rationale="tie-a",
            role="planner",
        ),
        consensus_module.AgentProposal(
            agent_id="a2",
            action="action_b",
            confidence=0.8,
            risk="low",
            rationale="tie-b",
            role="planner",
        ),
    ]
    first = engine.resolve(
        task_id="same-task",
        user_id="same-user",
        task_type="general",
        proposals=proposals,
        veto_policy="require_approval",
        explore_exploit_level=0.7,
    )
    second = engine.resolve(
        task_id="same-task",
        user_id="same-user",
        task_type="general",
        proposals=proposals,
        veto_policy="require_approval",
        explore_exploit_level=0.7,
    )
    assert first.selected_action in {"action_a", "action_b"}
    assert second.selected_action == first.selected_action
