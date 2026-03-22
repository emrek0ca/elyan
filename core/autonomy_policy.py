from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.command_hardening import classify_command_route


@dataclass
class AutonomyDecision:
    mode: str = "auto"
    should_ask: bool = False
    should_resume: bool = False
    reason: str = ""
    question: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "should_ask": self.should_ask,
            "should_resume": self.should_resume,
            "reason": self.reason,
            "question": self.question,
            "confidence": self.confidence,
        }


class AutonomyPolicy:
    """Normalize autonomy decisions for first-run, chat and side-effect workflows."""

    DEFAULT_ASKING_MODES = {"needs-consent", "needs-approval", "block"}

    def decide(
        self,
        user_input: str,
        *,
        quick_intent: Any = None,
        parsed_intent: dict[str, Any] | None = None,
        request_contract: dict[str, Any] | None = None,
        capability_plan: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> AutonomyDecision:
        route = classify_command_route(
            user_input,
            quick_intent=quick_intent,
            parsed_intent=parsed_intent,
            capability_domain=str(getattr(capability_plan, "domain", "") or ""),
            metadata=dict(metadata or {}),
        )
        low = str(user_input or "").strip().lower()
        contract = dict(request_contract or {})
        if route.refusal:
            return AutonomyDecision(
                mode="block",
                should_ask=True,
                reason=str(route.reason or "blocked"),
                question=str(route.refusal_message or route.reason or ""),
                confidence=float(route.confidence or 0.0),
            )
        if bool(route.should_clarify) or bool(contract.get("needs_clarification")):
            return AutonomyDecision(
                mode="auto-with-resume",
                should_ask=True,
                should_resume=True,
                reason=str(route.reason or "needs_clarification"),
                question=str(route.clarification_message or contract.get("clarifying_question") or "").strip(),
                confidence=float(route.confidence or 0.0),
            )
        if any(token in low for token in ("sil", "delete", "remove", "pay", "purchase", "post", "gönder", "gonder", "revoke", "disconnect")):
            return AutonomyDecision(
                mode="needs-approval",
                should_ask=True,
                reason="destructive_or_external_action",
                question="Bu işlem için onay gerekiyor. Devam edeyim mi?",
                confidence=max(0.8, float(route.confidence or 0.0)),
            )
        if contract.get("auth_strategy") or contract.get("required_scopes"):
            return AutonomyDecision(
                mode="needs-consent",
                should_ask=True,
                reason="oauth_or_scope_consent",
                question="Bu uygulamayı bağlamak için kısa bir yetkilendirme gerekiyor.",
                confidence=max(0.75, float(route.confidence or 0.0)),
            )
        if route.mode in {"communication", "screen", "browser", "file", "research", "code", "task"}:
            return AutonomyDecision(
                mode="auto",
                should_ask=False,
                reason=str(route.reason or "auto_route"),
                confidence=float(route.confidence or 0.0),
            )
        return AutonomyDecision(
            mode="auto-with-resume",
            should_ask=bool(route.should_clarify),
            should_resume=bool(route.should_clarify),
            reason=str(route.reason or "default"),
            question=str(route.clarification_message or "").strip(),
            confidence=float(route.confidence or 0.0),
        )


_AUTONOMY_POLICY: AutonomyPolicy | None = None


def get_autonomy_policy() -> AutonomyPolicy:
    global _AUTONOMY_POLICY
    if _AUTONOMY_POLICY is None:
        _AUTONOMY_POLICY = AutonomyPolicy()
    return _AUTONOMY_POLICY


__all__ = ["AutonomyDecision", "AutonomyPolicy", "get_autonomy_policy"]
