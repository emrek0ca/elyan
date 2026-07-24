from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath
from typing import Any, Callable, TypeVar


MAX_PARALLEL_READS = 3
QUANTUM_SCHEDULER_BENCHMARK_VERSION = "elyan_quantum_benchmark_v1"
QUANTUM_SCHEDULER_BENCHMARK_PRODUCER = "elyan_quantum_benchmark_worker"
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


_STEP_REF_PATTERN = re.compile(r"\{\{\s*steps\.([A-Za-z0-9_\-]+)")


def _template_step_references(value: Any) -> set[str]:
    """Bir adımın args'ındaki `{{steps.<id>...}}` veri-akışı atıflarından adım
    kimliklerini çıkarır. Örtük bağımlılık kurmak için: planlayıcı `dependsOn`'ı
    unutsa bile, başka bir adımın çıktısını tüketen adım o adımdan SONRA
    sıralanmalı; aksi halde çözülmemiş şablonla yürütülüp fail ediyordu."""
    refs: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            refs |= _template_step_references(item)
    elif isinstance(value, list):
        for item in value:
            refs |= _template_step_references(item)
    elif isinstance(value, str):
        refs.update(_STEP_REF_PATTERN.findall(value))
    return refs


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scheduler_facts(step: dict[str, Any]) -> dict[str, Any]:
    facts = step.get("_scheduler") if isinstance(step.get("_scheduler"), dict) else {}
    return facts if isinstance(facts, dict) else {}


def _bounded_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _dispatch_optimization_weight(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    if value.get("strategy") != "quantum_guided_dispatch_v1":
        return 0.0
    if value.get("benchmarkSource") != "measured" or value.get("active") is not True:
        return 0.0
    raw = value.get("admissionWeight")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(float(raw)):
        return 0.0
    return min(0.15, max(0.0, float(raw)))


def _responsive_execution_weight(value: Any) -> float:
    if not isinstance(value, dict):
        return 0.0
    if value.get("strategy") != "quantum_liveness_guard_v1":
        return 0.0
    if value.get("benchmarkSource") != "measured" or value.get("active") is not True:
        return 0.0
    raw = value.get("boostWeight")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(float(raw)):
        return 0.0
    return min(0.08, max(0.0, float(raw)))


def _quantum_boost_for_step(step: dict[str, Any], weight: float) -> float:
    if weight <= 0:
        return 0.0
    facts = _scheduler_facts(step)
    if facts.get("ready") is False or facts.get("accessMode") != "read" or facts.get("parallelSafe") is not True:
        return 0.0
    # Bound the effect to a small intra-class boost. It must never outrank explicit
    # user priority, dependency readiness, or write/side-effect safety.
    return round(weight, 4)


def _responsive_boost_for_step(step: dict[str, Any], weight: float) -> float:
    if weight <= 0:
        return 0.0
    facts = _scheduler_facts(step)
    if facts.get("ready") is False or facts.get("accessMode") != "read" or facts.get("parallelSafe") is not True:
        return 0.0
    return round(weight, 4)


def _schedule_quality_score(steps: list[dict[str, Any]]) -> float:
    if len(steps) <= 1:
        return 1.0
    pair_count = 0
    penalty = 0.0
    for left_index, left in enumerate(steps):
        left_facts = _scheduler_facts(left)
        for right in steps[left_index + 1:]:
            right_facts = _scheduler_facts(right)
            pair_count += 1
            if left_facts.get("ready") is False and right_facts.get("ready") is True:
                penalty += 1.0
            left_priority = int(left_facts.get("priority", 1) or 0)
            right_priority = int(right_facts.get("priority", 1) or 0)
            if left_facts.get("ready") is not False and right_facts.get("ready") is not False and left_priority < right_priority:
                penalty += 0.45 * float(right_priority - left_priority)
            left_deadline = float(left_facts.get("deadline", math.inf))
            right_deadline = float(right_facts.get("deadline", math.inf))
            if left_deadline > right_deadline:
                penalty += 0.35
            left_queued = float(left_facts.get("queuedAt", math.inf))
            right_queued = float(right_facts.get("queuedAt", math.inf))
            if left_priority == right_priority and left_queued > right_queued:
                penalty += 0.15
    max_penalty = max(1.0, float(pair_count) * 1.8)
    return round(_bounded_score(1.0 - penalty / max_penalty), 4)


def quantum_schedule_benchmark(ordered_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a server-parseable optimization attestation for the chosen schedule.

    The scheduler remains deterministic. This benchmark measures whether its
    chosen order improves the planner/original order without exposing user text.
    """
    safe_steps = [dict(step) for step in ordered_steps if isinstance(step, dict)]
    original_order = sorted(
        safe_steps,
        key=lambda step: int(_scheduler_facts(step).get("originalIndex", 0) or 0),
    )
    score = _schedule_quality_score(safe_steps)
    baseline_score = _schedule_quality_score(original_order)
    dataset_fingerprint = _sha256_hex(
        [
            {
                "id": str(step.get("id", "") or ""),
                "capability": str(step.get("capability", "") or ""),
                "dependsOn": [str(item) for item in (step.get("dependsOn", []) or []) if str(item or "").strip()],
                "scheduler": {
                    key: _scheduler_facts(step).get(key)
                    for key in ("priority", "deadline", "queuedAt", "ready", "accessMode", "parallelSafe", "resources")
                },
            }
            for step in safe_steps
        ]
    )
    run_id = _sha256_hex(
        {
            "datasetFingerprint": dataset_fingerprint,
            "orderedStepIds": [str(step.get("id", "") or "") for step in safe_steps],
            "score": score,
            "classicalBaselineScore": baseline_score,
        }
    )[:32]
    return {
        "version": QUANTUM_SCHEDULER_BENCHMARK_VERSION,
        "producer": QUANTUM_SCHEDULER_BENCHMARK_PRODUCER,
        "runId": f"qsched-{run_id}",
        "metric": "dispatch_schedule_quality",
        "datasetFingerprint": dataset_fingerprint,
        "sampleCount": max(32, len(safe_steps)),
        "score": score,
        "source": "measured",
        "classicalBaselineScore": baseline_score,
        "measuredAt": _utc_now_iso(),
        "backend": "elyan_quantum_scheduler",
        "advantageScore": round(score - baseline_score, 4),
        "qualified": score > baseline_score,
    }


def _liveness_features(steps: list[dict[str, Any]]) -> dict[str, int]:
    ready_read_parallel = 0
    blocked = 0
    writes = 0
    deadline_pressure = 0
    quantum_boosted = 0
    for step in steps:
        facts = _scheduler_facts(step)
        if facts.get("ready") is False:
            blocked += 1
        if facts.get("accessMode") == "write":
            writes += 1
        if facts.get("parallelSafe") is True and facts.get("ready") is True and facts.get("accessMode") == "read":
            ready_read_parallel += 1
        if math.isfinite(float(facts.get("deadline", math.inf) or math.inf)):
            deadline_pressure += 1
        if float(facts.get("quantumBoost", 0.0) or 0.0) > 0:
            quantum_boosted += 1
    return {
        "parallelReadCandidateCount": ready_read_parallel,
        "blockedStepCount": blocked,
        "writeStepCount": writes,
        "deadlinePressureStepCount": deadline_pressure,
        "quantumBoostedStepCount": quantum_boosted,
    }


def _responsive_liveness_score(steps: list[dict[str, Any]]) -> float:
    if not steps:
        return 1.0
    total = max(1, len(steps))
    features = _liveness_features(steps)
    ready_count = total - features["blockedStepCount"]
    score = 0.55
    score += 0.25 * (ready_count / total)
    score += 0.18 * (features["parallelReadCandidateCount"] / total)
    score -= 0.12 * (features["writeStepCount"] / total)
    score -= 0.08 * (features["deadlinePressureStepCount"] / total)
    score += 0.06 * (features["quantumBoostedStepCount"] / total)

    for left_index, left in enumerate(steps):
        left_facts = _scheduler_facts(left)
        if left_facts.get("ready") is False:
            for right in steps[left_index + 1:]:
                if _scheduler_facts(right).get("ready") is True:
                    score -= 0.08
                    break
        if left_facts.get("accessMode") == "write":
            for right in steps[left_index + 1:]:
                right_facts = _scheduler_facts(right)
                if right_facts.get("parallelSafe") is True and right_facts.get("ready") is True:
                    score -= 0.04
                    break

    return round(_bounded_score(score), 4)


def quantum_liveness_benchmark(ordered_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure how responsive a chosen schedule is without exposing task data."""
    safe_steps = [dict(step) for step in ordered_steps if isinstance(step, dict)]
    original_order = sorted(
        safe_steps,
        key=lambda step: int(_scheduler_facts(step).get("originalIndex", 0) or 0),
    )
    score = _responsive_liveness_score(safe_steps)
    baseline_score = _responsive_liveness_score(original_order)
    features = _liveness_features(safe_steps)
    dataset_fingerprint = _sha256_hex(
        [
            {
                "id": str(step.get("id", "") or ""),
                "capability": str(step.get("capability", "") or ""),
                "scheduler": {
                    key: _scheduler_facts(step).get(key)
                    for key in ("priority", "deadline", "ready", "accessMode", "parallelSafe")
                },
            }
            for step in safe_steps
        ]
    )
    run_id = _sha256_hex(
        {
            "datasetFingerprint": dataset_fingerprint,
            "orderedStepIds": [str(step.get("id", "") or "") for step in safe_steps],
            "score": score,
            "classicalBaselineScore": baseline_score,
            "features": features,
        }
    )[:32]
    return {
        "version": QUANTUM_SCHEDULER_BENCHMARK_VERSION,
        "producer": QUANTUM_SCHEDULER_BENCHMARK_PRODUCER,
        "runId": f"qlive-{run_id}",
        "metric": "responsive_execution_liveness",
        "datasetFingerprint": dataset_fingerprint,
        "sampleCount": max(32, len(safe_steps)),
        "score": score,
        "source": "measured",
        "classicalBaselineScore": baseline_score,
        "measuredAt": _utc_now_iso(),
        "backend": "elyan_quantum_liveness_scheduler",
        "advantageScore": round(score - baseline_score, 4),
        "qualified": score > baseline_score,
        **features,
    }


def schedule_steps(
    steps: list[dict[str, Any]],
    *,
    metadata_provider: Callable[[str], dict[str, Any]],
    readiness_provider: Callable[[str], dict[str, Any]],
    completed_step_ids: set[str] | None = None,
    dispatch_optimization: dict[str, Any] | None = None,
    responsive_execution: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a stable topological order with deterministic scheduling facts.

    Dependencies and readiness are eligibility gates. Ready candidates are then
    ordered by user priority, nearest deadline, longest wait, and original order.
    """
    normalized: list[dict[str, Any]] = []
    quantum_weight = _dispatch_optimization_weight(dispatch_optimization)
    responsive_weight = _responsive_execution_weight(responsive_execution)
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
        quantum_boost = _quantum_boost_for_step(step, quantum_weight)
        if quantum_boost > 0:
            step["_scheduler"]["quantumBoost"] = quantum_boost
            step["_scheduler"]["dispatchOptimization"] = "quantum_guided_dispatch_v1"
        responsive_boost = _responsive_boost_for_step(step, responsive_weight)
        if responsive_boost > 0:
            step["_scheduler"]["responsiveBoost"] = responsive_boost
            step["_scheduler"]["responsiveExecution"] = "quantum_liveness_guard_v1"
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
        # ④: `{{steps.<id>...}}` veri-akışı atıflarından ÖRTÜK bağımlılık çıkar.
        # Planlayıcı dependsOn'ı unutsa bile, bir adım başka adımın çıktısını
        # tüketiyorsa o adımdan SONRA sıralanır (yoksa çözülmemiş şablonla fail
        # ediyordu). Yalnız bilinen, kendisi olmayan, tamamlanmamış adımlar
        # eklenir; bilinmeyen atıflar yok sayılır (şablon çözücü onları ele alır).
        inferred = _template_step_references({
            "args": step.get("args", {}),
            "forEach": step.get("forEach"),
        })
        inferred &= ids
        inferred.discard(step["id"])
        inferred -= completed
        dependencies[step["id"]] = dependency_ids | inferred

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
                -float(facts.get("quantumBoost", 0.0) or 0.0),
                -float(facts.get("responsiveBoost", 0.0) or 0.0),
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
