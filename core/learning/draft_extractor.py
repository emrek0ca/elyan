from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PreferenceDraftCandidate:
    preference_key: str
    proposed_value: dict[str, Any]
    rationale: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SkillDraftCandidate:
    name_hint: str
    description: str
    trigger_text: str
    tool_names: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RoutineDraftCandidate:
    name_hint: str
    description: str
    trigger_text: str
    schedule_expression: str
    delivery_channel: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningDraftBatch:
    preference_updates: list[PreferenceDraftCandidate] = field(default_factory=list)
    skill_drafts: list[SkillDraftCandidate] = field(default_factory=list)
    routine_drafts: list[RoutineDraftCandidate] = field(default_factory=list)

    def has_items(self) -> bool:
        return bool(self.preference_updates or self.skill_drafts or self.routine_drafts)


_SHORT_RESPONSE_PATTERNS = (
    "kısa cevap",
    "kisa cevap",
    "kısa yaz",
    "kisa yaz",
    "özet geç",
    "ozet gec",
    "concise",
    "short answer",
)
_DETAILED_RESPONSE_PATTERNS = (
    "detaylı",
    "detayli",
    "ayrıntılı",
    "ayrintili",
    "teknik detay",
    "deep dive",
    "detailed",
)
_STRICT_APPROVAL_PATTERNS = (
    "önce sor",
    "once sor",
    "izinsiz",
    "onay almadan",
    "bana sormadan",
    "always ask",
    "ask first",
)
_RELAXED_APPROVAL_PATTERNS = (
    "küçük şeyler için sorma",
    "kucuk seyler icin sorma",
    "minor things without asking",
    "you can do small changes",
)
_AUTOMATION_PATTERNS = (
    "bunu otomatikleştir",
    "bunu otomatiklestir",
    "bunu skill yap",
    "teach you this",
    "remember this workflow",
    "her sabah",
    "her gün",
    "her gun",
    "every morning",
    "every day",
    "routine",
)


def _slugify_name(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9çğıöşü]+", "_", str(text or "").strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:48] or "workflow_draft"


def _extract_preference_candidates(user_input: str, action: str, channel: str) -> list[PreferenceDraftCandidate]:
    low = str(user_input or "").strip().lower()
    candidates: list[PreferenceDraftCandidate] = []
    if any(token in low for token in _SHORT_RESPONSE_PATTERNS):
        candidates.append(
            PreferenceDraftCandidate(
                preference_key="response_style",
                proposed_value={"explanation_style": "concise"},
                rationale="Kullanıcı kısa ve özet yanıt istedi.",
                confidence=0.94,
                metadata={"channel": channel, "action": action},
            )
        )
    if any(token in low for token in _DETAILED_RESPONSE_PATTERNS):
        candidates.append(
            PreferenceDraftCandidate(
                preference_key="response_style",
                proposed_value={"explanation_style": "technical"},
                rationale="Kullanıcı daha detaylı/teknik açıklama tercih etti.",
                confidence=0.92,
                metadata={"channel": channel, "action": action},
            )
        )
    if any(token in low for token in _STRICT_APPROVAL_PATTERNS):
        candidates.append(
            PreferenceDraftCandidate(
                preference_key="approval_style",
                proposed_value={"approval_sensitivity_hint": "strict"},
                rationale="Kullanıcı riskli işlemler için önce onay istedi.",
                confidence=0.95,
                metadata={"channel": channel, "action": action},
            )
        )
    if any(token in low for token in _RELAXED_APPROVAL_PATTERNS):
        candidates.append(
            PreferenceDraftCandidate(
                preference_key="approval_style",
                proposed_value={"approval_sensitivity_hint": "balanced"},
                rationale="Kullanıcı küçük değişikliklerde daha az onay istedi.",
                confidence=0.82,
                metadata={"channel": channel, "action": action},
            )
        )
    return candidates


def _extract_skill_draft_candidates(
    user_input: str,
    *,
    action: str,
    success: bool,
    tool_names: list[str],
    role: str,
    job_type: str,
    channel: str,
) -> list[SkillDraftCandidate]:
    if not success:
        return []
    low = str(user_input or "").strip().lower()
    if not any(token in low for token in _AUTOMATION_PATTERNS):
        return []
    title_seed = job_type or action or "workflow"
    name_hint = _slugify_name(title_seed)
    description = str(user_input or "").strip()[:240]
    confidence = 0.76
    if "skill" in low or "workflow" in low:
        confidence = 0.9
    elif "her sabah" in low or "every morning" in low or "routine" in low:
        confidence = 0.86
    return [
        SkillDraftCandidate(
            name_hint=name_hint,
            description=description or f"{title_seed} workflow draft",
            trigger_text=str(user_input or "").strip(),
            tool_names=[str(item).strip() for item in tool_names if str(item).strip()][:10],
            confidence=confidence,
            metadata={
                "channel": channel,
                "action": action,
                "role": role,
                "job_type": job_type,
            },
        )
    ]


def _extract_routine_draft_candidates(
    user_input: str,
    *,
    action: str,
    success: bool,
    channel: str,
) -> list[RoutineDraftCandidate]:
    if not success:
        return []
    text = str(user_input or "").strip()
    low = text.lower()
    if not any(token in low for token in _AUTOMATION_PATTERNS):
        return []
    try:
        from core.nl_cron import nl_cron

        parsed = nl_cron.parse(text)
    except Exception:
        parsed = None
    if not parsed:
        return []
    schedule_expression = str(parsed.get("cron") or "").strip()
    if not schedule_expression:
        return []
    original_task = str(parsed.get("original_task") or text).strip()
    return [
        RoutineDraftCandidate(
            name_hint=_slugify_name(original_task),
            description=original_task,
            trigger_text=text,
            schedule_expression=schedule_expression,
            delivery_channel=channel,
            confidence=0.88,
            metadata={"action": action, "channel": channel, "parser_type": str(parsed.get("type") or "")},
        )
    ]


def collect_learning_drafts(
    *,
    user_input: str,
    response_text: str,
    action: str,
    success: bool,
    context: dict[str, Any] | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> LearningDraftBatch:
    ctx = dict(context or {})
    meta = dict(runtime_metadata or {})
    channel = str(ctx.get("channel") or meta.get("channel") or meta.get("channel_type") or "cli")
    tool_results = list(ctx.get("tool_results") or [])
    tool_names = list(
        {
            str(item.get("tool") or item.get("action") or item.get("tool_name") or "").strip()
            for item in tool_results
            if isinstance(item, dict)
        }
        - {""}
    )
    if not tool_names and str(action or "").strip():
        tool_names = [str(action or "").strip()]
    _ = response_text
    return LearningDraftBatch(
        preference_updates=_extract_preference_candidates(str(user_input or ""), str(action or ""), channel),
        skill_drafts=_extract_skill_draft_candidates(
            str(user_input or ""),
            action=str(action or ""),
            success=bool(success),
            tool_names=tool_names,
            role=str(ctx.get("role") or ""),
            job_type=str(ctx.get("job_type") or ""),
            channel=channel,
        ),
        routine_drafts=_extract_routine_draft_candidates(
            str(user_input or ""),
            action=str(action or ""),
            success=bool(success),
            channel=channel,
        )
    )


__all__ = [
    "LearningDraftBatch",
    "PreferenceDraftCandidate",
    "RoutineDraftCandidate",
    "SkillDraftCandidate",
    "collect_learning_drafts",
]
