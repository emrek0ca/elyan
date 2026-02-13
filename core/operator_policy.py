"""
Operator autonomy policy and safety gates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OperatorPolicy:
    level: str
    allow_system_actions: bool
    allow_destructive_actions: bool
    require_confirmation_for_risky: bool


class OperatorPolicyEngine:
    """Maps autonomy level to executable safety policy."""

    _LEVELS = {"Advisory", "Assisted", "Confirmed", "Trusted", "Operator"}

    def resolve(self, level: str) -> OperatorPolicy:
        lv = str(level or "Confirmed").strip().title()
        if lv not in self._LEVELS:
            lv = "Confirmed"

        if lv == "Advisory":
            return OperatorPolicy(
                level=lv,
                allow_system_actions=False,
                allow_destructive_actions=False,
                require_confirmation_for_risky=True,
            )
        if lv == "Assisted":
            return OperatorPolicy(
                level=lv,
                allow_system_actions=True,
                allow_destructive_actions=False,
                require_confirmation_for_risky=True,
            )
        if lv == "Confirmed":
            return OperatorPolicy(
                level=lv,
                allow_system_actions=True,
                allow_destructive_actions=True,
                require_confirmation_for_risky=True,
            )
        if lv == "Trusted":
            return OperatorPolicy(
                level=lv,
                allow_system_actions=True,
                allow_destructive_actions=True,
                require_confirmation_for_risky=False,
            )
        # Operator
        return OperatorPolicy(
            level=lv,
            allow_system_actions=True,
            allow_destructive_actions=True,
            require_confirmation_for_risky=False,
        )


_operator_policy_engine: OperatorPolicyEngine | None = None


def get_operator_policy_engine() -> OperatorPolicyEngine:
    global _operator_policy_engine
    if _operator_policy_engine is None:
        _operator_policy_engine = OperatorPolicyEngine()
    return _operator_policy_engine
