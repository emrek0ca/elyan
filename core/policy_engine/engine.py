from typing import Any, Dict, List, Optional, Tuple
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger

slog = get_structured_logger("policy_engine")

class PolicyDecision:
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"

class PolicyEngine:
    """
    Evaluates actions against security and safety policies.
    """
    def __init__(self):
        self.rules = [] # Placeholder for dynamic rules

    def evaluate_action(self, capability: str, action: str, params: Dict[str, Any], risk_level: RiskLevel) -> Tuple[str, str]:
        """
        Determines the policy decision for a given action.
        Returns (decision, reason).
        """
        # 1. DENY rules (Highest priority)
        if capability == "terminal" and action == "execute":
            command = str(params.get("command", "")).lower()
            dangerous_patterns = ["rm -rf /", "sudo ", "mkfs", "dd if="]
            for pattern in dangerous_patterns:
                if pattern in command:
                    return PolicyDecision.DENY, f"Dangerous command pattern detected: {pattern}"

        # 2. APPROVAL rules
        if risk_level in {RiskLevel.DESTRUCTIVE, RiskLevel.SYSTEM_CRITICAL}:
            return PolicyDecision.REQUIRE_APPROVAL, f"Risk level {risk_level.value} requires explicit approval"
            
        if capability == "filesystem" and action in {"write_file", "trash_file"}:
            # For now, let's require approval for writes in sensitive dirs
            path = str(params.get("path", "")).lower()
            sensitive_dirs = [".ssh", ".aws", ".env", "/etc/", "/var/"]
            for s_dir in sensitive_dirs:
                if s_dir in path:
                    return PolicyDecision.REQUIRE_APPROVAL, f"Modification of sensitive path {s_dir} requires approval"

        # 3. ALLOW rules (Default for low risk)
        if risk_level == RiskLevel.READ_ONLY:
            return PolicyDecision.ALLOW, "Read-only actions are allowed by default"

        if risk_level == RiskLevel.WRITE_SAFE:
            return PolicyDecision.ALLOW, "Safe-write actions are allowed by default"

        # Default to require approval for anything not explicitly covered
        return PolicyDecision.REQUIRE_APPROVAL, "Action requires review by default (Safety First)"

# Global instance
policy_engine = PolicyEngine()
