from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "have",
    "will",
    "into",
    "your",
    "about",
    "you",
    "ile",
    "ve",
    "bir",
    "bu",
    "şu",
    "su",
    "birlikte",
    "için",
    "icin",
    "gibi",
    "ama",
    "veya",
}

_POSITIVE_EVENT_TYPES = {"like", "thumbs_up", "positive", "copy", "keep", "accepted_edit", "feedback_score"}
_NEGATIVE_EVENT_TYPES = {"dislike", "thumbs_down", "negative", "correction"}
_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "browser": ("browser", "web", "site", "sayfa", "open url", "navigate", "screenshot"),
    "database": ("database", "sql", "query", "schema", "migration", "opengauss", "postgres", "mysql"),
    "knowledge": ("research", "grounded", "brain", "rag", "retrieval", "quivr", "knowledge"),
    "code": ("code", "kod", "test", "refactor", "bug", "cli", "api"),
    "file": ("file", "dosya", "document", "doc", "pdf", "sheet", "excel", "word"),
    "workflow": ("workflow", "bundle", "plan", "task", "mission", "pipeline"),
    "messaging": ("telegram", "whatsapp", "slack", "discord", "signal", "mail", "email"),
}


def _record_value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _tokenize(texts: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        line = _normalize_text(raw).lower()
        if not line:
            continue
        for token in re.findall(r"[a-z0-9çğıöşü_/-]{3,}", line):
            if token in _STOPWORDS or token.startswith("http") or token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out


def _domain_from_text(text: str) -> str:
    low = _normalize_text(text).lower()
    if not low:
        return "general"
    for domain, markers in _DOMAIN_HINTS.items():
        if any(marker in low for marker in markers):
            return domain
    return "general"


def _task_history_states(task: Any) -> list[str]:
    history = list(_record_value(task, "history", []) or [])
    states: list[str] = []
    for event in history:
        state = _normalize_text(_record_value(event, "state", "")).lower()
        if state:
            states.append(state)
    return states


def _task_artifacts(task: Any) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for item in list(_record_value(task, "artifacts", []) or []):
        if isinstance(item, dict):
            artifacts.append(dict(item))
    return artifacts


def build_task_learning_snapshot(task: Any) -> dict[str, Any]:
    objective = _normalize_text(_record_value(task, "objective", ""))
    context = dict(_record_value(task, "context", {}) or {}) if isinstance(_record_value(task, "context", {}), dict) else {}
    state = _normalize_text(_record_value(task, "state", "pending")).lower() or "pending"
    history_states = _task_history_states(task)
    artifacts = _task_artifacts(task)
    artifact_types = Counter(str(item.get("type") or "artifact").strip().lower() for item in artifacts if str(item.get("path") or "").strip())
    created_at = float(_record_value(task, "created_at", 0.0) or 0.0)
    updated_at = float(_record_value(task, "updated_at", created_at or time.time()) or time.time())
    duration_seconds = max(0.0, updated_at - created_at) if created_at else 0.0
    artifact_count = len(artifacts)
    retry_count = max(0, len(history_states) - 1)
    domain = _domain_from_text(" ".join([objective, str(context.get("user_input") or ""), str(context.get("task_card") or "")]))

    if state == "completed":
        if artifact_count > 0:
            lesson = "Artifact-first verification worked; keep capturing proof."
            next_action = "Promote reusable skill/workflow"
        else:
            lesson = "Completed without artifacts; capture proof next time."
            next_action = "Add evidence capture before completion"
    elif state == "partial":
        lesson = "Partial completion means scope or evidence is missing."
        next_action = "Fill missing evidence and rerun verification"
    elif state == "failed":
        lesson = "Failure suggests the input or constraints need tightening."
        next_action = "Clarify scope, constraints, and execution route"
    elif state in {"executing", "verifying"}:
        lesson = "Execution is active; keep the loop small and verifiable."
        next_action = "Continue with smaller verified steps"
    else:
        lesson = "Planning state; define the smallest safe next step."
        next_action = "Plan the task before execution"

    domain_hint = ""
    if domain == "database":
        domain_hint = "Run read-only query before any mutation"
    elif domain == "browser":
        domain_hint = "Capture screenshot and trace before closing"
    elif domain == "knowledge":
        domain_hint = "Ground the answer with source-backed retrieval"
    elif domain == "code":
        domain_hint = "Add a focused test and verify the diff"

    confidence = 0.28
    if state == "completed":
        confidence += 0.32
    elif state == "partial":
        confidence += 0.18
    elif state == "failed":
        confidence += 0.08
    if artifact_count > 0:
        confidence += 0.14
    if retry_count <= 2:
        confidence += 0.08
    confidence = max(0.0, min(1.0, confidence))

    return {
        "objective": objective,
        "state": state,
        "domain": domain,
        "history_states": history_states[-6:],
        "transition_count": len(history_states),
        "artifact_count": artifact_count,
        "artifact_types": dict(artifact_types),
        "duration_seconds": round(duration_seconds, 2),
        "retry_count": retry_count,
        "lesson": lesson,
        "next_action": next_action,
        "domain_hint": domain_hint,
        "confidence": round(confidence, 3),
        "summary": f"{state}: {objective[:96]}",
    }


def _feedback_summary(feedback_events: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(item.get("reward", 0.0) or 0.0) for item in feedback_events]
    correction_hints: list[dict[str, Any]] = []
    for item in feedback_events:
        event_type = str(item.get("event_type") or "").strip().lower()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if event_type == "correction":
            correction_hints.append(
                {
                    "wrong_action": str(metadata.get("wrong_action") or "").strip(),
                    "corrected_text": str(metadata.get("corrected_text") or "").strip(),
                    "reason": str(metadata.get("source") or "correction").strip(),
                }
            )
    positive_count = sum(1 for item in feedback_events if str(item.get("event_type") or "").strip().lower() in _POSITIVE_EVENT_TYPES or float(item.get("reward", 0.0) or 0.0) > 0)
    negative_count = sum(1 for item in feedback_events if str(item.get("event_type") or "").strip().lower() in _NEGATIVE_EVENT_TYPES or float(item.get("reward", 0.0) or 0.0) < 0)
    correction_count = sum(1 for item in feedback_events if str(item.get("event_type") or "").strip().lower() == "correction")
    return {
        "feedback_count": len(feedback_events),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "correction_count": correction_count,
        "avg_reward": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
        "correction_hints": correction_hints[:5],
    }


def build_user_learning_digest(
    user_id: str,
    *,
    tasks: list[Any] | None = None,
    feedback_events: list[dict[str, Any]] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    request_text: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    uid = str(user_id or "local")
    task_rows = list(tasks or [])[: max(1, int(limit or 10))]
    snapshots = [build_task_learning_snapshot(task) for task in task_rows]
    feedback_rows = [dict(row) for row in list(feedback_events or []) if isinstance(row, dict)]
    feedback_summary = _feedback_summary(feedback_rows)
    runtime_profile = dict(runtime_profile or {})

    objectives = [snapshot.get("objective") or _record_value(task, "objective", "") for snapshot, task in zip(snapshots, task_rows)]
    request_text = _normalize_text(request_text)
    tokens = _tokenize([*objectives, request_text, runtime_profile.get("top_topics", []), runtime_profile.get("preferred_topics", [])])
    token_counts = Counter(tokens)
    top_topics = [token for token, _ in token_counts.most_common(6)]

    state_counts = Counter(snapshot.get("state") for snapshot in snapshots if snapshot.get("state"))
    completed_count = int(state_counts.get("completed", 0))
    partial_count = int(state_counts.get("partial", 0))
    failed_count = int(state_counts.get("failed", 0))
    task_count = len(snapshots)
    artifact_total = sum(int(snapshot.get("artifact_count", 0) or 0) for snapshot in snapshots)
    success_rate = round(completed_count / max(task_count, 1), 4)
    average_artifacts = round(artifact_total / max(task_count, 1), 3)
    dominant_domain = snapshots[0].get("domain", "general") if snapshots else _domain_from_text(request_text)
    if dominant_domain == "general" and top_topics:
        dominant_domain = top_topics[0]

    action_counts = Counter()
    for task in task_rows:
        context = _record_value(task, "context", {}) or {}
        if isinstance(context, dict):
            action_counts[str(context.get("action") or context.get("job_type") or context.get("channel") or "").strip() or "task"] += 1
        else:
            action_counts["task"] += 1
    top_actions = [{"action": action, "count": count} for action, count in action_counts.most_common(5)]

    recent_lessons = []
    for snapshot in snapshots[:5]:
        lesson = str(snapshot.get("lesson") or "").strip()
        if lesson and lesson not in recent_lessons:
            recent_lessons.append(lesson)

    notes: list[str] = []
    if runtime_profile.get("preferred_language"):
        notes.append(f"Preferred language: {runtime_profile.get('preferred_language')}")
    if runtime_profile.get("response_length_bias"):
        notes.append(f"Response length bias: {runtime_profile.get('response_length_bias')}")
    notes.append(f"Success rate: {int(success_rate * 100)}%")
    notes.append(f"Feedback signals: {feedback_summary['feedback_count']}")
    if feedback_summary["correction_count"] > 0:
        notes.append("Correction hints available; load them before planning.")
    if failed_count > completed_count:
        notes.append("Ask for one clarifying detail before execution.")
    elif partial_count > 0:
        notes.append("Fill evidence gaps before marking completion.")
    if average_artifacts <= 0.0 and task_count > 0:
        notes.append("Capture evidence artifacts by default.")
    if completed_count >= 3 and top_topics:
        notes.append("Promote this repeated pattern into a reusable skill/workflow.")
    if dominant_domain in {"browser", "database", "knowledge", "code"}:
        notes.append(f"Primary domain: {dominant_domain}.")

    next_actions: list[dict[str, Any]] = []
    if feedback_summary["correction_count"] > 0:
        next_actions.append(
            {
                "title": "Load correction hints",
                "description": "Recent corrections should be injected into runtime context before planning.",
                "priority": "high",
                "reason": "correction_history",
            }
        )
    if failed_count > completed_count:
        next_actions.append(
            {
                "title": "Clarify scope",
                "description": "Ask for one concrete constraint before executing the next task.",
                "priority": "high",
                "reason": "failure_bias",
            }
        )
    if partial_count > 0:
        next_actions.append(
            {
                "title": "Close evidence gap",
                "description": "Capture missing artifacts or verification evidence before completion.",
                "priority": "medium",
                "reason": "partial_completion",
            }
        )
    if completed_count >= 3 and top_topics:
        next_actions.append(
            {
                "title": "Promote reusable workflow",
                "description": f"Repeat the {top_topics[0]} pattern as a skill or workflow bundle.",
                "priority": "medium",
                "reason": "repeated_success",
            }
        )
    if dominant_domain == "browser":
        next_actions.append(
            {
                "title": "Default to screenshots",
                "description": "For browser work, capture screenshots and trace artifacts by default.",
                "priority": "low",
                "reason": "browser_domain",
            }
        )
    elif dominant_domain == "database":
        next_actions.append(
            {
                "title": "Prefer read-only SQL",
                "description": "Run read-only queries before any database mutation.",
                "priority": "low",
                "reason": "database_domain",
            }
        )
    elif dominant_domain == "knowledge":
        next_actions.append(
            {
                "title": "Use grounded retrieval",
                "description": "Anchor answers on source-backed retrieval and citations.",
                "priority": "low",
                "reason": "knowledge_domain",
            }
        )

    prompt_lines = notes[:5]
    if recent_lessons:
        prompt_lines.append("Recent lessons: " + " | ".join(recent_lessons[:3]))
    if top_topics:
        prompt_lines.append("Top topics: " + ", ".join(top_topics[:5]))
    prompt_hint = "\n".join(f"- {line}" for line in prompt_lines if str(line).strip())

    learning_score = 0.0
    learning_score += success_rate * 0.55
    learning_score += max(-1.0, min(1.0, feedback_summary["avg_reward"])) * 0.2 + 0.2
    if artifact_total > 0:
        learning_score += 0.15
    if feedback_summary["correction_count"] > 0:
        learning_score -= 0.05
    learning_score = max(0.0, min(1.0, learning_score))

    return {
        "user_id": uid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_count": task_count,
        "completed_count": completed_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
        "success_rate": success_rate,
        "artifact_count": artifact_total,
        "average_artifacts": average_artifacts,
        "top_topics": top_topics,
        "top_actions": top_actions,
        "dominant_domain": dominant_domain,
        "feedback_summary": feedback_summary,
        "task_snapshots": snapshots[:5],
        "recent_lessons": recent_lessons[:5],
        "learning_notes": notes[:10],
        "next_actions": next_actions[:5],
        "prompt_hint": prompt_hint,
        "learning_score": round(learning_score, 3),
        "request_text": request_text,
    }


__all__ = ["build_task_learning_snapshot", "build_user_learning_digest"]
