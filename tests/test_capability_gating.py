"""
Capability Gating Tests
Verify that Phase 6 features are properly gated in operator mode.
"""

import os
import pytest
from core.capability_gating import (
    CapabilityGate,
    OperatorMode,
    get_capability_gate,
    is_operator_mode,
    is_advanced_mode,
)


@pytest.fixture
def reset_gate():
    """Reset the capability gate singleton between tests."""
    import core.capability_gating
    core.capability_gating._capability_gate = None
    yield
    core.capability_gating._capability_gate = None


def test_capability_gate_operator_mode_default(reset_gate):
    """Test: Operator mode is the default."""
    # Clear env to default
    os.environ.pop("ELYAN_OPERATOR_MODE", None)
    gate = CapabilityGate()
    assert gate.mode == OperatorMode.OPERATOR
    assert gate.is_operator_mode()
    assert not gate.is_advanced_mode()


def test_capability_gate_advanced_mode(reset_gate, monkeypatch):
    """Test: Advanced mode can be enabled via env var."""
    monkeypatch.setenv("ELYAN_OPERATOR_MODE", "advanced")
    gate = CapabilityGate()
    assert gate.mode == OperatorMode.ADVANCED
    assert gate.is_advanced_mode()
    assert not gate.is_operator_mode()


def test_operator_mode_disables_phase6(reset_gate):
    """Test: Phase 6 features are disabled in operator mode."""
    gate = CapabilityGate()
    assert not gate.check_research_enabled()
    assert not gate.check_vision_enabled()
    assert not gate.check_code_intel_enabled()
    assert not gate.check_workflow_enabled()


def test_advanced_mode_enables_phase6(reset_gate, monkeypatch):
    """Test: Phase 6 features are enabled in advanced mode."""
    monkeypatch.setenv("ELYAN_OPERATOR_MODE", "advanced")
    gate = CapabilityGate()
    assert gate.check_research_enabled()
    assert gate.check_vision_enabled()
    assert gate.check_code_intel_enabled()
    assert gate.check_workflow_enabled()


def test_should_use_research_operator_mode(reset_gate):
    """Test: Research is not triggered in operator mode."""
    gate = CapabilityGate()
    assert not gate.should_use_research("research quantum computing")
    assert not gate.should_use_research("search for answers")


def test_should_use_research_advanced_mode(reset_gate, monkeypatch):
    """Test: Research is triggered in advanced mode."""
    monkeypatch.setenv("ELYAN_OPERATOR_MODE", "advanced")
    gate = CapabilityGate()
    assert gate.should_use_research("research quantum computing")
    assert gate.should_use_research("search for answers")


def test_should_use_code_intel_operator_mode(reset_gate):
    """Test: Code intelligence is not triggered in operator mode."""
    gate = CapabilityGate()
    assert not gate.should_use_code_intel("analyze this code")
    assert not gate.should_use_code_intel("generate tests")


def test_should_use_code_intel_advanced_mode(reset_gate, monkeypatch):
    """Test: Code intelligence is triggered in advanced mode."""
    monkeypatch.setenv("ELYAN_OPERATOR_MODE", "advanced")
    gate = CapabilityGate()
    assert gate.should_use_code_intel("analyze this code")
    assert gate.should_use_code_intel("generate tests")


def test_singleton_pattern(reset_gate):
    """Test: get_capability_gate returns singleton."""
    gate1 = get_capability_gate()
    gate2 = get_capability_gate()
    assert gate1 is gate2


def test_helper_functions(reset_gate):
    """Test: Helper functions work correctly."""
    assert is_operator_mode() is True
    assert is_advanced_mode() is False


def test_repr(reset_gate):
    """Test: String representation."""
    gate = CapabilityGate()
    assert "CapabilityGate(operator)" in repr(gate)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
