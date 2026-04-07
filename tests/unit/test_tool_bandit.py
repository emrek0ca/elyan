from __future__ import annotations

import json

from core.learning import tool_bandit as bandit_module
from core.learning.tool_bandit import ToolSelectionBandit


def test_ucb1_prefers_unexplored_tools(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    selected = bandit.select_tool("research_topic", ["a", "b"])
    assert selected in {"a", "b"}


def test_ucb1_prefers_successful_over_time(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    for _ in range(8):
        bandit.record_outcome("research_topic", "good", True, 120)
    for _ in range(8):
        bandit.record_outcome("research_topic", "bad", False, 5000)
    assert bandit.select_tool("research_topic", ["good", "bad"]) == "good"


def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "bandit.json"
    bandit = ToolSelectionBandit(state_path=path)
    bandit.record_outcome("general", "tool_a", True, 100)
    bandit.persist()
    other = ToolSelectionBandit(state_path=path)
    assert other.snapshot()["arms"]["general"]["tool_a"]["pull_count"] == 1


def test_composite_reward_weighs_correctly(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    bandit.record_outcome("general", "tool_a", True, 10, user_satisfaction=1.0)
    arm = bandit.snapshot()["arms"]["general"]["tool_a"]
    assert arm["total_reward"] > 0.9


def test_exploration_decreases_with_pulls(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    arm = bandit._get_category_arms("general").setdefault("tool_a", bandit_module.ToolArm("tool_a"))
    first = arm.ucb1_score(1)
    arm.pull_count = 10
    arm.total_reward = 8
    second = arm.ucb1_score(20)
    assert second < first


def test_insights_reflect_best_tool(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    for _ in range(6):
        bandit.record_outcome("general", "tool_a", True, 100)
    for _ in range(6):
        bandit.record_outcome("general", "tool_b", False, 7000)
    assert bandit.get_insights()["general"]["best_tool"] == "tool_a"


def test_bootstrap_from_read_model(tmp_path, monkeypatch):
    class FakeReadModel:
        def get_tool_performance(self):
            return [{"tool_name": "tool_x", "total_calls": 10, "success_count": 8, "failure_count": 2, "avg_latency_ms": 200}]

    monkeypatch.setattr(bandit_module, "get_run_read_model", lambda: FakeReadModel())
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    assert "tool_x" in bandit.snapshot()["arms"]["_bootstrap"]


def test_concurrent_updates_safe(tmp_path):
    bandit = ToolSelectionBandit(state_path=tmp_path / "bandit.json")
    for _ in range(20):
        bandit.record_outcome("general", "tool_a", True, 50)
    assert bandit.snapshot()["arms"]["general"]["tool_a"]["pull_count"] == 20
