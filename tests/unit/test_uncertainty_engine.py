from __future__ import annotations

from core.reasoning.uncertainty_engine import Belief, UncertaintyEngine


def test_bayes_update_increases_confidence(tmp_path):
    engine = UncertaintyEngine(state_path=tmp_path / "beliefs.json")
    before = engine.beliefs["web_search_works"].probability
    after = engine.update_belief("web_search_works", "success", 0.95)
    assert after >= before


def test_below_threshold_requests_approval(tmp_path):
    engine = UncertaintyEngine(state_path=tmp_path / "beliefs.json")
    engine.beliefs["file_delete_safe"] = Belief("file_delete_safe", 0.1)
    assert engine.should_ask_approval("file_delete_safe") is True


def test_above_threshold_skips_approval(tmp_path):
    engine = UncertaintyEngine(state_path=tmp_path / "beliefs.json")
    engine.beliefs["web_search_works"] = Belief("web_search_works", 0.99)
    assert engine.should_ask_approval("web_search_works") is False


def test_explain_uncertainty_informative(tmp_path):
    engine = UncertaintyEngine(state_path=tmp_path / "beliefs.json")
    explanation = engine.explain_uncertainty("web_search_works")
    assert "güvenle" in explanation


def test_priors_initialized_correctly(tmp_path):
    engine = UncertaintyEngine(state_path=tmp_path / "beliefs.json")
    assert engine.beliefs["web_search_works"].probability > engine.beliefs["file_delete_safe"].probability


def test_belief_persistence(tmp_path):
    path = tmp_path / "beliefs.json"
    engine = UncertaintyEngine(state_path=path)
    engine.update_belief("network_request_safe", "success", 0.9)
    engine.update_belief("network_request_safe", "success", 0.9)
    engine.update_belief("network_request_safe", "success", 0.9)
    engine.update_belief("network_request_safe", "success", 0.9)
    engine.update_belief("network_request_safe", "success", 0.9)
    other = UncertaintyEngine(state_path=path)
    assert "network_request_safe" in other.snapshot()
