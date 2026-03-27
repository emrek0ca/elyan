from core.security.contracts import DataClassification, ExecutionTier, decision_for, execution_tier_for
from core.tool_schemas_registry import get_schema_registry


def test_execution_tier_mapping_respects_risk_and_classification():
    assert execution_tier_for("read_only", DataClassification.INTERNAL) == ExecutionTier.OBSERVE
    assert execution_tier_for("write_safe", DataClassification.INTERNAL) == ExecutionTier.SAFE_SANDBOX
    assert execution_tier_for("write_sensitive", DataClassification.INTERNAL) == ExecutionTier.SENSITIVE_HOST
    assert execution_tier_for("read_only", DataClassification.SECRET) == ExecutionTier.SENSITIVE_HOST
    assert execution_tier_for("destructive", DataClassification.INTERNAL) == ExecutionTier.DESTRUCTIVE


def test_security_decision_includes_dry_validation_and_recovery_expectations():
    decision = decision_for(
        allowed=True,
        requires_approval=True,
        risk_level="write_sensitive",
        legacy_risk="guarded",
        data={"token": "secret-value"},
        reason="tool contract test",
    ).to_dict()

    assert decision["execution_tier"] == ExecutionTier.SENSITIVE_HOST.value
    assert decision["verification_policy"]["requires_dry_validation"] is True
    assert decision["verification_policy"]["requires_recovery_plan"] is True


def test_tool_contract_exposes_operational_metadata():
    registry = get_schema_registry()

    write_contract = registry.get_contract("write_file")
    assert write_contract["required_permissions"] == ["filesystem.write"]
    assert write_contract["execution_tier"] == ExecutionTier.SAFE_SANDBOX.value
    assert write_contract["rollback_strategy"]
    assert "verify path exists" in write_contract["verification_method"]

    automate_contract = registry.get_contract("vision_automate")
    assert automate_contract["execution_tier"] == ExecutionTier.SENSITIVE_HOST.value
    assert "evidence_screenshots" in automate_contract["expected_artifacts"]
    assert "sandbox" in " ".join(automate_contract["preconditions"]).lower()
