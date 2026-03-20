from __future__ import annotations

import re
from typing import Any

from .base import (
    AuthStrategy,
    FallbackPolicy,
    IntegrationType,
    WorkflowBundle,
    WorkflowStep,
    normalize_items,
)


def split_compound_text(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    numbered = re.split(r"(?:^|\s)(?:\d+[\)\.\-:])\s*", raw)
    candidates = [c.strip(" \n\t-•") for c in numbered if str(c).strip(" \n\t-•")]
    if len(candidates) >= 2:
        return candidates
    lines = [ln.strip(" \n\t-•") for ln in raw.splitlines() if ln.strip(" \n\t-•")]
    if len(lines) >= 2:
        return lines
    joined = re.split(r"\s+(?:ve|sonra|ardından|ardindan|then|and|y sonra)\s+", raw, flags=re.IGNORECASE)
    joined = [c.strip(" \n\t-•") for c in joined if str(c).strip(" \n\t-•")]
    if len(joined) >= 2:
        return joined
    return [raw]


def infer_action(step_text: str) -> str:
    low = str(step_text or "").lower()
    if any(token in low for token in ("mail", "email", "e-posta", "inbox")):
        if any(token in low for token in ("send", "gönder", "gonder", "posta at", "mail at")):
            return "send_email"
        if any(token in low for token in ("create", "yaz", "draft", "taslak")):
            return "draft_email"
        return "read_email"
    if any(token in low for token in ("calendar", "takvim", "remind", "hatırlat", "hatirlat", "event")):
        if any(token in low for token in ("create", "ekle", "oluştur", "olustur", "add")):
            return "create_event"
        return "list_events"
    if any(token in low for token in ("whatsapp", "instagram", "x.com", "twitter", "telegram")):
        if any(token in low for token in ("send", "gönder", "gonder", "post", "share", "yayınla", "yayinla")):
            return "social_post"
        return "social_read"
    if any(token in low for token in ("search", "araştır", "arastir", "research", "incele")):
        return "research"
    if any(token in low for token in ("open", "aç", "ac", "launch", "başlat", "baslat")):
        return "open"
    if any(token in low for token in ("write", "yaz", "create", "oluştur", "olustur", "make")):
        return "write"
    if any(token in low for token in ("delete", "sil", "remove", "post", "publish", "share")):
        return "destructive_or_publish"
    return "operate"


def infer_role(step_text: str, action: str) -> str:
    low = str(step_text or "").lower()
    if action in {"research"} or any(token in low for token in ("research", "araştır", "arastir", "source", "benchmark")):
        return "researcher"
    if action in {"send_email", "draft_email", "social_post"} or any(token in low for token in ("mail", "email", "social", "whatsapp", "instagram", "x.com")):
        return "communicator"
    if action in {"create_event", "list_events"} or any(token in low for token in ("calendar", "takvim", "remind", "hatırlat", "hatirlat")):
        return "ops"
    if action in {"write", "open", "operate"}:
        return "builder"
    return "lead"


def _requires_approval(action: str, step_text: str) -> bool:
    low = f"{action} {step_text}".lower()
    return any(token in low for token in ("delete", "sil", "remove", "post", "publish", "share", "send_email", "social_post"))


def _latency_level(integration_type: IntegrationType, action: str, step_text: str) -> str:
    if integration_type in {IntegrationType.BROWSER, IntegrationType.DESKTOP, IntegrationType.SOCIAL}:
        return "real_time"
    if action in {"open", "write"}:
        return "fast"
    if any(token in f"{action} {step_text}".lower() for token in ("research", "calendar", "email")):
        return "medium"
    return "standard"


def build_workflow_bundle(
    text: str,
    *,
    integration_type: IntegrationType | str = IntegrationType.UNKNOWN,
    provider: str = "",
    name: str = "",
    approval_level: int = 0,
    fallback_policy: FallbackPolicy | str = FallbackPolicy.AUTO,
    source: str = "heuristic",
    tags: list[str] | None = None,
    objective: str = "",
) -> WorkflowBundle:
    latency_rank = {"standard": 0, "fast": 1, "medium": 2, "real_time": 3}
    steps_text = split_compound_text(text)
    itype = integration_type if isinstance(integration_type, IntegrationType) else IntegrationType(str(integration_type or "unknown").strip().lower() or "unknown")
    bundle_id = re.sub(r"[^a-z0-9]+", "_", str(name or objective or text or "workflow").lower()).strip("_") or "workflow_bundle"
    objective_text = str(objective or text or "").strip()
    steps: list[WorkflowStep] = []
    roles: list[str] = []
    serial_steps: list[str] = []
    parallel_groups: list[list[str]] = []
    previous_id = ""
    parallel_candidate: list[str] = []

    for idx, step_text in enumerate(steps_text, start=1):
        action = infer_action(step_text)
        role = infer_role(step_text, action)
        roles.append(role)
        step_id = f"step_{idx}"
        requires_approval = _requires_approval(action, step_text)
        parallelizable = not requires_approval and action not in {"send_email", "social_post", "destructive_or_publish"}
        params = {
            "text": step_text,
            "action": action,
            "provider": provider,
        }
        if action in {"open", "write"}:
            params["goal"] = step_text
        step = WorkflowStep(
            step_id=step_id,
            title=step_text[:120] or f"Step {idx}",
            action=action,
            role=role,
            depends_on=[previous_id] if previous_id else [],
            parallelizable=parallelizable,
            requires_approval=requires_approval,
            parameters=params,
            evidence={
                "requires_artifact": action in {"write", "send_email", "social_post", "create_event"},
                "preferred_signal": "artifact" if action in {"write", "send_email", "social_post", "create_event"} else "state",
            },
            notes=[
                f"latency:{_latency_level(itype, action, step_text)}",
            ],
        )
        steps.append(step)
        if not parallel_candidate:
            parallel_candidate.append(step_id)
        else:
            if parallelizable and steps[-2].parallelizable:
                parallel_candidate.append(step_id)
            else:
                if len(parallel_candidate) > 1:
                    parallel_groups.append(list(parallel_candidate))
                parallel_candidate = [step_id]
        if not parallelizable:
            serial_steps.append(step_id)
        previous_id = step_id

    if len(parallel_candidate) > 1:
        parallel_groups.append(list(parallel_candidate))

    multi_agent_recommended = len(steps) >= 2 or any(role in {"researcher", "ops", "communicator"} for role in roles)
    evidence_contract = {
        "requires_artifact": any(step.evidence.get("requires_artifact") for step in steps),
        "requires_verification": True,
        "preferred_signal": "artifact" if any(step.evidence.get("requires_artifact") for step in steps) else "state",
    }
    output_artifacts = []
    if any(step.action in {"write", "send_email", "social_post", "create_event"} for step in steps):
        output_artifacts.append("artifact_or_receipt")
    if any(step.action == "research" for step in steps):
        output_artifacts.append("source_manifest")
    if any(step.action in {"open", "operate"} for step in steps):
        output_artifacts.append("state_snapshot")

    estimated_latency_level = "standard"
    best_latency_rank = -1
    for step in steps:
        latency_value = "standard"
        if step.notes:
            latency_value = str(step.notes[0].split(":", 1)[1] if ":" in step.notes[0] else step.notes[0]).strip() or "standard"
        rank = latency_rank.get(latency_value, 0)
        if rank > best_latency_rank:
            best_latency_rank = rank
            estimated_latency_level = latency_value

    return WorkflowBundle(
        bundle_id=bundle_id,
        name=str(name or bundle_id.replace("_", " ").title()),
        objective=objective_text,
        integration_type=itype,
        provider=str(provider or ""),
        roles=normalize_items(roles),
        steps=steps,
        serial_steps=normalize_items(serial_steps),
        parallel_groups=[normalize_items(group) for group in parallel_groups if group],
        multi_agent_recommended=multi_agent_recommended,
        approval_level=int(approval_level or 0),
        fallback_policy=fallback_policy if isinstance(fallback_policy, FallbackPolicy) else FallbackPolicy(str(fallback_policy or "auto").strip().lower() or "auto"),
        evidence_contract=evidence_contract,
        output_artifacts=normalize_items(output_artifacts),
        dependencies=[],
        source=source,
        tags=normalize_items(tags or []),
        metadata={
            "step_count": len(steps),
            "parallel_groups": len(parallel_groups),
        },
        estimated_latency_level=estimated_latency_level,
    )
