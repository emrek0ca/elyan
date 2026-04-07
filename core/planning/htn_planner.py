from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("htn_planner")


@dataclass(slots=True)
class Task:
    name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    preconditions: List[str] = field(default_factory=list)
    is_primitive: bool = False


@dataclass(slots=True)
class Method:
    task_name: str
    preconditions: List[str] = field(default_factory=list)
    subtasks: List[Task] = field(default_factory=list)
    ordering: str = "sequential"


def _default_state_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/htn_method_library.json")).expanduser()


class HTNPlanner:
    def __init__(self, state_path: str | Path | None = None):
        self.state_path = Path(state_path or _default_state_path()).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.method_library: Dict[str, List[Method]] = {}
        self.plan_cache: Dict[str, List[Task]] = {}
        self._load()
        self._load_domain_knowledge()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            for task_name, methods in raw.get("method_library", {}).items():
                parsed: List[Method] = []
                for method in methods or []:
                    if not isinstance(method, dict):
                        continue
                    parsed.append(
                        Method(
                            task_name=str(method.get("task_name") or task_name),
                            preconditions=list(method.get("preconditions") or []),
                            subtasks=[
                                Task(
                                    name=str(task.get("name") or ""),
                                    parameters=dict(task.get("parameters") or {}),
                                    preconditions=list(task.get("preconditions") or []),
                                    is_primitive=bool(task.get("is_primitive", False)),
                                )
                                for task in list(method.get("subtasks") or [])
                                if isinstance(task, dict)
                            ],
                            ordering=str(method.get("ordering") or "sequential"),
                        )
                    )
                if parsed:
                    self.method_library[task_name] = parsed
        except Exception as exc:
            slog.log_event("htn_load_error", {"error": str(exc)}, level="warning")

    def _persist(self) -> None:
        try:
            payload = {
                "method_library": {
                    task_name: [
                        {
                            **asdict(method),
                            "subtasks": [asdict(task) for task in method.subtasks],
                        }
                        for method in methods
                    ]
                    for task_name, methods in self.method_library.items()
                }
            }
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception as exc:
            slog.log_event("htn_persist_error", {"error": str(exc)}, level="warning")

    def _load_domain_knowledge(self) -> None:
        with self._lock:
            if self.method_library:
                return
            self.method_library = {
                "research_topic": [
                    Method(
                        task_name="research_topic",
                        subtasks=[
                            Task(name="web_search", parameters={"num_results": 5}, is_primitive=True),
                            Task(name="extract_key_facts", is_primitive=True),
                            Task(name="cross_verify", is_primitive=True),
                            Task(name="synthesize_answer", is_primitive=True),
                        ],
                    )
                ],
                "execute_code_task": [
                    Method(
                        task_name="execute_code_task",
                        subtasks=[
                            Task(name="analyze_codebase", is_primitive=True),
                            Task(name="write_implementation", is_primitive=True),
                            Task(name="run_tests", is_primitive=True),
                            Task(name="fix_if_failing", is_primitive=False),
                        ],
                    )
                ],
                "summarize_document": [
                    Method(
                        task_name="summarize_document",
                        subtasks=[
                            Task(name="read_document", is_primitive=True),
                            Task(name="extract_sections", is_primitive=True),
                            Task(name="generate_summary", is_primitive=True),
                        ],
                    )
                ],
                "file_operation_task": [
                    Method(
                        task_name="file_operation_task",
                        subtasks=[
                            Task(name="check_permissions", is_primitive=True),
                            Task(name="backup_if_needed", is_primitive=True),
                            Task(name="execute_operation", is_primitive=True),
                            Task(name="verify_result", is_primitive=True),
                        ],
                    )
                ],
            }

    async def plan(self, high_level_task: str, world_state: Dict[str, Any]) -> List[Task]:
        task_name = self._normalize_task_name(high_level_task)
        semantic_hash = self._semantic_hash(high_level_task)
        with self._lock:
            if semantic_hash in self.plan_cache:
                return list(self.plan_cache[semantic_hash])
        try:
            plan = await self._decompose(task_name, world_state or {})
        except Exception:
            plan = await self._llm_decompose(high_level_task, world_state or {})
        with self._lock:
            self.plan_cache[semantic_hash] = list(plan)
        return plan

    async def _decompose(self, task_name: str, state: Dict[str, Any]) -> List[Task]:
        methods = self.method_library.get(task_name, [])
        for method in methods:
            if not self._preconditions_met(method.preconditions, state):
                continue
            tasks: List[Task] = []
            for subtask in method.subtasks:
                if subtask.is_primitive:
                    tasks.append(subtask)
                else:
                    tasks.extend(await self._decompose(subtask.name, state))
            return tasks
        return await self._llm_decompose(task_name, state)

    async def _llm_decompose(self, task_name: str, state: Dict[str, Any]) -> List[Task]:
        return [Task(name=task_name, parameters={"state_hint": bool(state)}, is_primitive=True)]

    def record_successful_plan(self, task_name: str, plan: List[Task]) -> None:
        with self._lock:
            method = Method(task_name=self._normalize_task_name(task_name), subtasks=list(plan))
            self.method_library.setdefault(method.task_name, []).append(method)
            self._persist()

    def _normalize_task_name(self, task: str) -> str:
        return re.sub(r"\s+", "_", str(task or "").strip().lower())

    def _preconditions_met(self, preconditions: List[str], state: Dict[str, Any]) -> bool:
        available = {str(key).lower() for key, value in state.items() if bool(value)}
        for condition in preconditions:
            if str(condition).strip().lower() not in available:
                return False
        return True

    def _semantic_hash(self, task: str) -> str:
        low = str(task or "").lower()
        stopwords = {
            "ve", "bir", "için", "hakkında", "bilgi", "ver", "ara", "arastir", "araştır", "araştırma",
            "yap", "nasıl", "nasil", "how", "to", "the", "incele", "öğren", "ogren", "konu", "ile",
        }
        tokens = [token for token in re.findall(r"[a-z0-9çğıöşü]+", low) if token not in stopwords]
        normalized = " ".join(tokens) or low
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_htn_planner: Optional[HTNPlanner] = None


def get_htn_planner() -> HTNPlanner:
    global _htn_planner
    if _htn_planner is None:
        _htn_planner = HTNPlanner()
    return _htn_planner
