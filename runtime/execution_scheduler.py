from __future__ import annotations

import datetime as dt
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath
from typing import Any, Callable, TypeVar


MAX_PARALLEL_READS = 3
_T = TypeVar("_T")
_R = TypeVar("_R")

_PRIORITY_RANK = {
    "low": 0,
    "normal": 1,
    "medium": 1,
    "high": 2,
    "urgent": 3,
    "critical": 3,
}
_RESOURCE_ARG_KEYS = (
    "path",
    "inputPath",
    "input_path",
    "outputPath",
    "output_path",
    "directory",
    "workspace",
    "projectPath",
    "project_path",
    "url",
    "appName",
    "app_name",
    "serverId",
    "server_id",
    "recipient",
    "calendarId",
    "calendar_id",
)


class SchedulerPlanError(ValueError):
    pass


def _timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return math.inf
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return math.inf
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def _priority(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, min(3, int(value)))
    return _PRIORITY_RANK.get(str(value or "normal").strip().lower(), 1)


def _resource_keys(step: dict[str, Any]) -> tuple[str, ...]:
    explicit = step.get("resourceScope")
    values = explicit if isinstance(explicit, list) else [explicit] if explicit is not None else []
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    values.extend(args.get(key) for key in _RESOURCE_ARG_KEYS if args.get(key) is not None)

    resources: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if "/" in text or "\\" in text:
            try:
                text = str(PurePath(text))
            except (TypeError, ValueError):
                pass
        normalized = text.casefold()
        if normalized not in resources:
            resources.append(normalized)
    return tuple(resources)


def _contains_template(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_template(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_template(item) for item in value)
    return isinstance(value, str) and "{{" in value


def schedule_steps(
    steps: list[dict[str, Any]],
    *,
    metadata_provider: Callable[[str], dict[str, Any]],
    readiness_provider: Callable[[str], dict[str, Any]],
    completed_step_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return a stable topological order with deterministic scheduling facts.

    Dependencies and readiness are eligibility gates. Ready candidates are then
    ordered by user priority, nearest deadline, longest wait, and original order.
    """
    normalized: list[dict[str, Any]] = []
    completed = set(completed_step_ids or set())
    ids: set[str] = set(completed)
    for index, raw in enumerate(steps):
        step = dict(raw)
        step_id = str(step.get("id", "") or f"step_{index + 1}").strip()
        if not step_id or step_id in ids:
            raise SchedulerPlanError("duplicate_or_empty_step_id")
        ids.add(step_id)
        step["id"] = step_id
        capability = str(step.get("capability", "") or "").strip()
        metadata = metadata_provider(capability)
        readiness = readiness_provider(capability)
        side_effect = bool(metadata.get("sideEffect", False))
        requested_access = str(step.get("accessMode", "") or "").strip().lower()
        # A planner may make a read more restrictive, but can never downgrade a
        # registry-declared side effect into a parallel read.
        access_mode = "write" if side_effect or requested_access == "write" else "read"
        step["_scheduler"] = {
            "originalIndex": index,
            "priority": _priority(step.get("userPriority", step.get("priority", "normal"))),
            "deadline": _timestamp(step.get("deadlineAt", step.get("deadline", step.get("dueAt")))),
            "queuedAt": _timestamp(step.get("queuedAt", step.get("createdAt", step.get("enqueuedAt")))),
            "ready": bool(readiness.get("ready", readiness.get("available", True))),
            "accessMode": access_mode,
            "resources": _resource_keys(step),
            "parallelSafe": (
                access_mode == "read"
                and step.get("forEach") is None
                and not _contains_template(step.get("args", {}))
            ),
        }
        normalized.append(step)

    by_id = {step["id"]: step for step in normalized}
    dependencies: dict[str, set[str]] = {}
    for step in normalized:
        raw_dependencies = step.get("dependsOn", [])
        raw_dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        dependency_ids = {str(item or "").strip() for item in raw_dependencies if str(item or "").strip()}
        unknown = dependency_ids - ids
        if unknown:
            raise SchedulerPlanError("missing_dependency")
        dependencies[step["id"]] = dependency_ids

    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set(completed)
    while len(ordered) < len(normalized):
        candidates = [
            step for step in normalized
            if step["id"] not in resolved and dependencies[step["id"]] <= resolved
        ]
        if not candidates:
            raise SchedulerPlanError("dependency_cycle")

        def sort_key(step: dict[str, Any]) -> tuple[Any, ...]:
            facts = step["_scheduler"]
            return (
                0 if facts["ready"] else 1,
                -int(facts["priority"]),
                float(facts["deadline"]),
                float(facts["queuedAt"]),
                int(facts["originalIndex"]),
                str(step["id"]),
            )

        selected = min(candidates, key=sort_key)
        ordered.append(by_id[selected["id"]])
        resolved.add(selected["id"])
    return ordered


def parallel_read_batch(
    steps: list[dict[str, Any]],
    start_index: int,
    *,
    completed_step_ids: set[str],
    limit: int = MAX_PARALLEL_READS,
) -> list[dict[str, Any]]:
    """Select only consecutive, ready, independent read steps.

    Writes are never returned, so same-resource writes remain serialized. A
    dependency on another member also prevents the steps sharing a batch.
    """
    batch: list[dict[str, Any]] = []
    batch_ids: set[str] = set()
    for step in steps[start_index:]:
        if len(batch) >= max(1, min(MAX_PARALLEL_READS, limit)):
            break
        facts = step.get("_scheduler") if isinstance(step.get("_scheduler"), dict) else {}
        if facts.get("accessMode") != "read" or facts.get("parallelSafe") is not True or facts.get("ready") is not True:
            break
        dependencies = {
            str(item or "").strip()
            for item in (step.get("dependsOn", []) or [])
            if str(item or "").strip()
        }
        if not dependencies <= completed_step_ids or dependencies & batch_ids:
            break
        batch.append(step)
        batch_ids.add(str(step.get("id", "") or ""))
    return batch if len(batch) > 1 else []


def _task_value(task: dict[str, Any], *keys: str) -> Any:
    containers: list[dict[str, Any]] = [task]
    for container in containers:
        if len(containers) >= 16:
            break
        for nested_key in ("payload", "metadata", "desktopWorkOrder", "planPreview", "goalContract"):
            nested = container.get(nested_key)
            if isinstance(nested, dict) and all(nested is not known for known in containers):
                containers.append(nested)
    for container in containers:
        for key in keys:
            if container.get(key) is not None:
                return container.get(key)
    return None


def schedule_tasks(
    tasks: list[dict[str, Any]],
    *,
    readiness_provider: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Deterministically order backend-assigned tasks without changing ownership.

    Execution remains serial in RemoteTaskRunner, so conflicting writes can
    never overlap. Dependencies are honored among tasks present in the batch.
    """
    normalized = [dict(task) for task in tasks if isinstance(task, dict)]
    ids = {str(task.get("id", "") or "").strip() for task in normalized}
    if "" in ids or len(ids) != len(normalized):
        raise SchedulerPlanError("duplicate_or_empty_task_id")

    dependencies: dict[str, set[str]] = {}
    facts: dict[str, tuple[Any, ...]] = {}
    for index, task in enumerate(normalized):
        task_id = str(task["id"])
        raw_dependencies = _task_value(task, "dependsOn", "dependencies")
        raw_dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        declared_dependencies = {
            str(item or "").strip() for item in raw_dependencies if str(item or "").strip()
        }
        unknown_dependencies = declared_dependencies - ids
        dependencies[task_id] = declared_dependencies & ids
        explicitly_resolved = _task_value(task, "dependenciesReady", "prerequisitesCompleted") is True
        if unknown_dependencies and not explicitly_resolved:
            task["_schedulerBlockedReason"] = "unknown_dependency"
        ready = readiness_provider(task) if readiness_provider is not None else bool(_task_value(task, "ready") is not False)
        ready = ready and "_schedulerBlockedReason" not in task
        facts[task_id] = (
            0 if ready else 1,
            -_priority(_task_value(task, "userPriority", "priority")),
            _timestamp(_task_value(task, "deadlineAt", "deadline", "dueAt")),
            _timestamp(_task_value(task, "queuedAt", "createdAt", "enqueuedAt")),
            index,
            task_id,
        )

    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set()
    while len(ordered) < len(normalized):
        candidates = [
            task for task in normalized
            if str(task["id"]) not in resolved and dependencies[str(task["id"])] <= resolved
        ]
        if not candidates:
            raise SchedulerPlanError("task_dependency_cycle")
        selected = min(candidates, key=lambda task: facts[str(task["id"])])
        ordered.append(selected)
        resolved.add(str(selected["id"]))
    return ordered


def run_parallel(items: list[_T], worker: Callable[[_T], _R], *, limit: int = MAX_PARALLEL_READS) -> list[_R]:
    worker_count = max(1, min(MAX_PARALLEL_READS, limit, len(items)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="elyan-read") as pool:
        futures = [pool.submit(worker, item) for item in items]
        return [future.result() for future in futures]
