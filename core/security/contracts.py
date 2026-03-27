from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from security.privacy_guard import redact_text, sanitize_object


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class ApprovalPolicy(str, Enum):
    NONE = "none"
    CONDITIONAL = "conditional"
    REQUIRED = "required"


class CloudEligibility(str, Enum):
    LOCAL_ONLY = "local_only"
    ALLOW_REDACTED = "allow_redacted"
    ALLOW = "allow"


class ExecutionTier(str, Enum):
    OBSERVE = "observe"
    SAFE_SANDBOX = "safe_sandbox"
    SENSITIVE_HOST = "sensitive_host"
    DESTRUCTIVE = "destructive"


_SECRET_KEY_PATTERNS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "secret_key",
    "password",
    "private_key",
    "bearer",
    "authorization",
    "cookie",
    "session",
    "csrf",
}

_SENSITIVE_KEY_PATTERNS = {
    "email",
    "phone",
    "address",
    "identity",
    "ssh",
    "wallet",
    "iban",
    "card",
    "credential",
    "provider",
    "approval",
    "payload",
    "tool_calls",
    "steps",
    "memory",
}

_SECRET_VALUE_PATTERNS = [
    re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9._-]{10,}\.[a-zA-Z0-9._-]{10,}\b"),
    re.compile(r"\b(?:sk|pk|rk|api|token|key)[-_]?[a-zA-Z0-9]{12,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
]


def _contains_pattern(value: str, patterns: set[str]) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return any(token in normalized for token in patterns)


def classify_value(value: Any, *, key: str = "") -> DataClassification:
    if _contains_pattern(key, _SECRET_KEY_PATTERNS):
        return DataClassification.SECRET
    if _contains_pattern(key, _SENSITIVE_KEY_PATTERNS):
        return DataClassification.SENSITIVE

    if isinstance(value, str):
        text = str(value)
        lowered = text.lower()
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(text):
                return DataClassification.SECRET
        if any(token in lowered for token in ("password", "api key", "secret", "bearer ", "authorization:", ".env")):
            return DataClassification.SECRET
        if redact_text(text) != text:
            return DataClassification.SENSITIVE
        return DataClassification.INTERNAL if text else DataClassification.PUBLIC

    if isinstance(value, dict):
        highest = DataClassification.PUBLIC
        for child_key, child_value in value.items():
            highest = max_classification(highest, classify_value(child_value, key=str(child_key)))
        return highest

    if isinstance(value, (list, tuple, set)):
        highest = DataClassification.PUBLIC
        for item in value:
            highest = max_classification(highest, classify_value(item))
        return highest

    if value is None:
        return DataClassification.PUBLIC

    return DataClassification.INTERNAL


def max_classification(left: DataClassification, right: DataClassification) -> DataClassification:
    order = {
        DataClassification.PUBLIC: 0,
        DataClassification.INTERNAL: 1,
        DataClassification.SENSITIVE: 2,
        DataClassification.SECRET: 3,
    }
    return left if order[left] >= order[right] else right


def contains_sensitive_data(value: Any) -> bool:
    return classify_value(value) in {DataClassification.SENSITIVE, DataClassification.SECRET}


def execution_tier_for(risk_level: str, classification: DataClassification) -> ExecutionTier:
    token = str(risk_level or "").strip().lower()
    if token in {"destructive"}:
        return ExecutionTier.DESTRUCTIVE
    if token in {"write_sensitive", "system_critical"}:
        return ExecutionTier.SENSITIVE_HOST
    if classification in {DataClassification.SENSITIVE, DataClassification.SECRET}:
        return ExecutionTier.SENSITIVE_HOST
    if token in {"write_safe", "guarded"}:
        return ExecutionTier.SAFE_SANDBOX
    return ExecutionTier.OBSERVE


def redact_for_cloud(value: Any) -> tuple[Any, list[str]]:
    classification = classify_value(value)
    if classification == DataClassification.PUBLIC:
        return value, []
    if classification == DataClassification.INTERNAL:
        return sanitize_object(value), []
    if classification == DataClassification.SENSITIVE:
        return sanitize_object(value), ["sensitive_redaction"]
    return sanitize_object(value), ["secret_redaction"]


@dataclass(slots=True)
class SecurityDecision:
    allowed: bool
    requires_approval: bool = False
    risk_level: str = "read_only"
    execution_tier: ExecutionTier = ExecutionTier.OBSERVE
    data_classification: DataClassification = DataClassification.INTERNAL
    approval_policy: ApprovalPolicy = ApprovalPolicy.CONDITIONAL
    audit_requirement: str = "standard"
    cloud_eligibility: CloudEligibility = CloudEligibility.LOCAL_ONLY
    verification_policy: dict[str, Any] = field(default_factory=dict)
    reason: str = "ok"
    source: str = "security_contract"
    legacy_risk: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "execution_tier": self.execution_tier.value,
            "data_classification": self.data_classification.value,
            "approval_policy": self.approval_policy.value,
            "audit_requirement": self.audit_requirement,
            "cloud_eligibility": self.cloud_eligibility.value,
            "verification_policy": dict(self.verification_policy),
            "reason": self.reason,
            "source": self.source,
        }
        if self.legacy_risk is not None:
            payload["risk"] = self.legacy_risk
        return payload


def decision_for(
    *,
    allowed: bool,
    requires_approval: bool,
    risk_level: str,
    legacy_risk: str,
    data: Any = None,
    reason: str = "ok",
    source: str = "security_contract",
) -> SecurityDecision:
    classification = classify_value(data)
    if risk_level in {"destructive", "system_critical", "write_sensitive"} or classification == DataClassification.SECRET:
        approval_policy = ApprovalPolicy.REQUIRED
    elif requires_approval:
        approval_policy = ApprovalPolicy.CONDITIONAL
    else:
        approval_policy = ApprovalPolicy.NONE

    if classification == DataClassification.SECRET:
        cloud = CloudEligibility.LOCAL_ONLY
    elif classification == DataClassification.SENSITIVE:
        cloud = CloudEligibility.ALLOW_REDACTED
    else:
        cloud = CloudEligibility.ALLOW

    audit_requirement = "high" if risk_level in {"destructive", "system_critical", "write_sensitive"} or classification in {DataClassification.SENSITIVE, DataClassification.SECRET} else "standard"
    execution_tier = execution_tier_for(risk_level, classification)

    verification_policy = {
        "requires_verification": risk_level != "read_only",
        "requires_preview": risk_level in {"write_sensitive", "destructive", "system_critical"},
        "requires_rollback_metadata": risk_level in {"write_safe", "write_sensitive", "destructive", "system_critical"},
        "requires_dry_validation": execution_tier != ExecutionTier.OBSERVE,
        "requires_recovery_plan": execution_tier in {ExecutionTier.SENSITIVE_HOST, ExecutionTier.DESTRUCTIVE},
    }
    return SecurityDecision(
        allowed=allowed,
        requires_approval=requires_approval,
        risk_level=str(risk_level or "read_only"),
        execution_tier=execution_tier,
        data_classification=classification,
        approval_policy=approval_policy,
        audit_requirement=audit_requirement,
        cloud_eligibility=cloud,
        verification_policy=verification_policy,
        reason=reason,
        source=source,
        legacy_risk=legacy_risk,
    )


__all__ = [
    "ApprovalPolicy",
    "CloudEligibility",
    "DataClassification",
    "ExecutionTier",
    "SecurityDecision",
    "classify_value",
    "contains_sensitive_data",
    "decision_for",
    "execution_tier_for",
    "max_classification",
    "redact_for_cloud",
]
