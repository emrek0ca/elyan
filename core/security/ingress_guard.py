from __future__ import annotations

from typing import Any, Dict, Optional

from core.events.event_store import EventType
from core.security.prompt_firewall import PromptInjectionFirewall


BLOCKED_INGRESS_TEXT = (
    "İstek güvenlik politikası nedeniyle durduruldu. "
    "Mesajı tek amaçlı, açık ve gizli talimat içermeyecek şekilde yeniden gönder."
)


def blocked_ingress_text(_: Optional[Dict[str, Any]] = None) -> str:
    return BLOCKED_INGRESS_TEXT


def _record_security_decision(platform_origin: str, verdict: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> None:
    try:
        from core.elyan_runtime import get_elyan_runtime

        meta = dict(metadata or {})
        aggregate_id = str(
            meta.get("run_id")
            or meta.get("session_id")
            or meta.get("user_id")
            or platform_origin
            or "security"
        ).strip() or "security"
        payload = {
            "platform": str(platform_origin or ""),
            "allowed": bool(verdict.get("allowed", True)),
            "reason": str(verdict.get("reason", "ok") or "ok"),
            "method": str(verdict.get("method", "unknown") or "unknown"),
            "tainted": bool(verdict.get("tainted", False)),
            "channel_type": str(meta.get("channel_type") or ""),
            "channel_id": str(meta.get("channel_id") or ""),
            "user_id": str(meta.get("user_id") or ""),
            "session_id": str(meta.get("session_id") or ""),
            "run_id": str(meta.get("run_id") or ""),
        }
        get_elyan_runtime().record_event(
            event_type=EventType.SECURITY_DECISION_MADE,
            aggregate_id=aggregate_id,
            aggregate_type="security",
            payload=payload,
        )
    except Exception:
        return


async def inspect_ingress(
    text: str,
    *,
    platform_origin: str,
    agent: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    retrieved_context: str = "",
    tool_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = str(text or "")
    if not raw.strip():
        verdict = {"allowed": True, "reason": "empty", "method": "bypass", "tainted": False}
        _record_security_decision(platform_origin, verdict, metadata)
        return verdict

    firewall = PromptInjectionFirewall(agent)
    try:
        verdict = await firewall.inspect(
            raw,
            platform_origin,
            retrieved_context=retrieved_context,
            tool_args=tool_args,
        )
    except Exception as exc:
        verdict = {
            "allowed": True,
            "reason": "firewall_degraded",
            "method": "degraded",
            "tainted": False,
            "error": str(exc),
        }
    _record_security_decision(platform_origin, verdict, metadata)
    return verdict
