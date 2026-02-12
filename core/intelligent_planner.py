"""
Intelligent Task Planning & Multi-Step Execution
Advanced task decomposition, dependency management, parallel execution
"""

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from utils.logger import get_logger

logger = get_logger("intelligent_planner")


class TaskPriority(Enum):
    """Task execution priority"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class TaskState(Enum):
    """Task execution state"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


@dataclass
class ExecutionContext:
    """Context for task execution"""
    variables: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubTask:
    """Represents a decomposed sub-task"""
    task_id: str
    name: str
    action: str
    params: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[Any] = None
    error: Optional[str] = None
    rollback_action: Optional[Callable] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    estimated_duration: float = 10.0  # seconds


@dataclass
class ExecutionPlan:
    """Complete execution plan for a complex task"""
    plan_id: str
    description: str
    subtasks: List[SubTask]
    context: ExecutionContext = field(default_factory=ExecutionContext)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    total_duration: float = 0.0
    success: bool = False


class IntelligentPlanner:
    """
    Intelligent Task Planning & Execution System
    - Decomposes complex tasks into subtasks
    - Manages dependencies
    - Executes tasks in parallel where possible
    - Supports rollback on failure
    - Tracks progress and estimates completion
    """

    def __init__(self):
        self.active_plans: Dict[str, ExecutionPlan] = {}
        self.plan_history: deque = deque(maxlen=100)
        self.executor_pool_size = 4
        self.progress_callbacks: List[Callable] = []
        from core.llm_client import LLMClient
        self.llm = LLMClient()
        # Cost-guard defaults (overridable via TaskEngine)
        self.use_llm = True

        logger.info("Intelligent Planner initialized")

    def register_progress_callback(self, callback: Callable):
        """Register callback for progress updates"""
        self.progress_callbacks.append(callback)

    async def decompose_task(
        self,
        task_description: str,
        llm_client=None,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True
    ) -> List[SubTask]:
        """
        Decompose a complex task into executable subtasks
        Uses LLM for intelligent decomposition
        """
        client = llm_client or self.llm
        subtasks: List[SubTask] = []

        # LLM-assisted decomposition first
        if use_llm and client:
            try:
                context_hint = self._format_context_for_planner(context or {})
                prompt = f"""Goal: {task_description}

Plan 3-10 executable steps. Use valid actions (open_url, advanced_research, read_file, write_file, take_screenshot, create_folder, list_files, run_safe_command, send_email, analyze_document, web_search, generate_report).
Return JSON array:
[{{"id":"task_1","name":"...","action":"tool","params":{{"path":"~/Desktop"}},"depends_on":[]}}]
"""
                if context_hint:
                    prompt += f"\nContext: {context_hint}"

                resp = await client.generate(prompt, max_tokens=600)
                subtasks = self._parse_subtasks_from_response(resp, task_description, limit=10)
            except Exception as e:
                logger.debug(f"LLM decomposition failed, fallback heuristic: {e}")

        # Heuristic fallback
        if not subtasks:
            if "ve" in task_description or "sonra" in task_description:
                parts = task_description.replace(" sonra ", " ve ").split(" ve ")
                for i, part in enumerate(parts):
                    subtasks.append(SubTask(
                        task_id=f"subtask_{i+1}",
                        name=part.strip(),
                        action=self._infer_action(part.strip()),
                        params={},
                        dependencies=[f"subtask_{i}"] if i > 0 else [],
                        priority=TaskPriority.NORMAL
                    ))
            else:
                subtasks.append(SubTask(
                    task_id="subtask_1",
                    name=task_description,
                    action=self._infer_action(task_description),
                    params={},
                    priority=TaskPriority.NORMAL
                ))

        logger.info(f"Decomposed task into {len(subtasks)} subtasks")
        return subtasks

    def _parse_subtasks_from_response(self, response_text: str, task_description: str, limit: int = 10) -> List[SubTask]:
        import json
        import re

        subtasks: List[SubTask] = []
        match = re.search(r"\[[\s\S]*\]", str(response_text), re.DOTALL)
        if not match:
            return subtasks
        actions = json.loads(match.group())
        if not isinstance(actions, list):
            return subtasks

        for i, a in enumerate(actions[:limit]):
            if not isinstance(a, dict):
                continue
            action = str(a.get("action", "")).split("(")[0].strip() or self._infer_action(task_description)
            deps = a.get("depends_on", []) or a.get("dependencies", [])
            if isinstance(deps, str):
                deps = [deps]
            if not isinstance(deps, list):
                deps = []
            subtasks.append(
                SubTask(
                    task_id=str(a.get("id", f"subtask_{i+1}")),
                    name=str(a.get("name", f"Adim {i+1}")),
                    action=action,
                    params=a.get("params", {}) if isinstance(a.get("params", {}), dict) else {},
                    dependencies=[str(d) for d in deps if str(d).strip()],
                    priority=TaskPriority.NORMAL,
                )
            )
        return subtasks

    def _format_context_for_planner(self, context: Dict[str, Any]) -> str:
        if not context:
            return ""
        segments: list[str] = []
        profile = context.get("user_profile") or {}
        if isinstance(profile, dict) and profile:
            pref_lang = profile.get("preferred_language", "auto")
            top_topics = ", ".join(profile.get("top_topics", [])[:5])
            top_actions = ", ".join(profile.get("top_actions", [])[:5])
            segments.append(f"user_profile.language={pref_lang}")
            if top_topics:
                segments.append(f"user_profile.top_topics={top_topics}")
            if top_actions:
                segments.append(f"user_profile.top_actions={top_actions}")

        prefs = context.get("user_preferences") or {}
        if isinstance(prefs, dict):
            lang = prefs.get("preferred_language")
            if lang:
                segments.append(f"user_preferences.preferred_language={lang}")

        formatted = context.get("formatted_context")
        if formatted:
            segments.append(f"recent_context={str(formatted)[:300]}")
        requirements = context.get("execution_requirements")
        if isinstance(requirements, dict) and requirements:
            req = ",".join(f"{k}={v}" for k, v in requirements.items())
            segments.append(f"execution_requirements={req[:200]}")
        return " | ".join(segments)

    def evaluate_plan_quality(self, subtasks: List[SubTask], goal: str = "") -> Dict[str, Any]:
        """Score plan quality before execution."""
        if not subtasks:
            return {"score": 0.0, "issues": ["no_subtasks"], "safe_to_run": False}

        issues: List[str] = []
        score = 1.0

        # 1) Action validity
        chat_count = sum(1 for t in subtasks if t.action == "chat")
        if chat_count == len(subtasks):
            issues.append("all_chat_actions")
            score -= 0.5
        elif chat_count > 0:
            issues.append("contains_chat_actions")
            score -= 0.15

        # 2) Dependency sanity
        known_ids = {t.task_id for t in subtasks}
        for t in subtasks:
            for dep in t.dependencies:
                if dep not in known_ids:
                    issues.append("invalid_dependency")
                    score -= 0.1
                    break

        # 3) Parameter completeness for common risky actions
        required_keys = {
            "open_url": ("url",),
            "write_file": ("path",),
            "read_file": ("path",),
            "delete_file": ("path",),
            "move_file": ("source", "destination"),
            "copy_file": ("source", "destination"),
        }
        for t in subtasks:
            req = required_keys.get(t.action)
            if not req:
                continue
            missing = [k for k in req if not str(t.params.get(k, "")).strip()]
            if missing:
                issues.append(f"missing_params:{t.task_id}:{','.join(missing)}")
                score -= 0.1

        # 4) Overly long plan heuristic
        if len(subtasks) > 10:
            issues.append("too_many_steps")
            score -= 0.1

        score = max(0.0, min(1.0, score))
        safe_to_run = score >= 0.55 and "all_chat_actions" not in issues
        return {"score": score, "issues": issues, "safe_to_run": safe_to_run}

    async def revise_plan(
        self,
        goal: str,
        *,
        current_subtasks: List[SubTask],
        context: Optional[Dict[str, Any]] = None,
        failure_feedback: str = "",
        llm_client=None,
        use_llm: bool = True,
    ) -> List[SubTask]:
        """Try a second-pass plan synthesis using failure feedback."""
        if not use_llm:
            return current_subtasks
        client = llm_client or self.llm
        if not client:
            return current_subtasks

        try:
            compact_plan = [
                {
                    "id": s.task_id,
                    "action": s.action,
                    "params": s.params,
                    "depends_on": s.dependencies,
                }
                for s in current_subtasks[:10]
            ]
            context_hint = self._format_context_for_planner(context or {})
            prompt = (
                f"Goal: {goal}\n"
                f"Current Plan JSON: {compact_plan}\n"
                f"Failure Feedback: {failure_feedback or 'quality_issues'}\n"
                "Revise this plan for higher success probability.\n"
                "Rules: use only valid tool-like actions, keep dependencies valid, fill required params.\n"
                "Return JSON array only."
            )
            if context_hint:
                prompt += f"\nContext: {context_hint}"

            resp = await client.generate(prompt, max_tokens=650)
            revised = self._parse_subtasks_from_response(resp, goal, limit=10)
            if revised:
                return revised
        except Exception as exc:
            logger.debug(f"Plan revision failed: {exc}")
        return current_subtasks

    def _infer_action(self, task_text: str) -> str:
        """Infer action from task text"""
        text_lower = task_text.lower()

        # Deterministic keyword mapping for planner fallback.
        action_map = {
            "oku": "read_file",
            "yaz": "write_file",
            "kaydet": "write_file",
            "sil": "delete_file",
            "taşı": "move_file",
            "tasi": "move_file",
            "kopyala": "copy_file",
            "aç": "open_app",
            "ac": "open_app",
            "kapat": "close_app",
            "araştır": "advanced_research",
            "arastir": "advanced_research",
            "ara": "web_search",
            "search": "web_search",
            "youtube": "open_url",
            "google": "open_url",
            "safari": "open_url",
            "site": "write_file",
            "html": "write_file",
            "klasör": "create_folder",
            "klasor": "create_folder",
            "listele": "list_files",
            "göster": "list_files",
            "goster": "list_files",
            "screenshot": "take_screenshot",
            "ekran": "take_screenshot",
        }

        for keyword, action in action_map.items():
            if keyword in text_lower:
                return action

        if "http" in text_lower or ".com" in text_lower or ".org" in text_lower:
            return "open_url"

        # Last-resort fallback should never become a non-tool hallucination.
        return "chat"

    async def create_plan(
        self,
        description: str,
        subtasks: Optional[List[SubTask]] = None,
        llm_client=None,
        context: Optional[Dict[str, Any]] = None,
        use_llm: bool = True
    ) -> ExecutionPlan:
        """Create and return an execution plan (returns the plan object)."""
        plan_id = str(uuid.uuid4())[:8]

        if not subtasks:
            # Decompose automatically
            subtasks = await self.decompose_task(description, llm_client, context=context, use_llm=use_llm and self.use_llm)

        plan = ExecutionPlan(
            plan_id=plan_id,
            description=description,
            subtasks=subtasks
        )

        self.active_plans[plan_id] = plan
        logger.info(f"Created plan {plan_id}: {description}")

        return plan

    def _build_dependency_graph(self, subtasks: List[SubTask]) -> Dict[str, Set[str]]:
        """Build dependency graph for task execution order"""
        graph = defaultdict(set)

        for task in subtasks:
            for dep in task.dependencies:
                graph[task.task_id].add(dep)

        return graph

    def _topological_sort(self, subtasks: List[SubTask]) -> List[List[str]]:
        """
        Topological sort to determine execution levels
        Returns list of levels where each level can be executed in parallel
        """
        graph = self._build_dependency_graph(subtasks)
        in_degree = {task.task_id: len(task.dependencies) for task in subtasks}

        levels = []
        ready = [task.task_id for task in subtasks if in_degree[task.task_id] == 0]

        while ready:
            levels.append(ready[:])
            next_ready = []

            for task_id in ready:
                # Find tasks that depend on this one
                for task in subtasks:
                    if task_id in task.dependencies:
                        in_degree[task.task_id] -= 1
                        if in_degree[task.task_id] == 0:
                            next_ready.append(task.task_id)

            ready = next_ready

        return levels

    async def execute_plan(
        self,
        plan_id: str,
        executor=None
    ) -> Dict[str, Any]:
        """Execute a plan with intelligent scheduling"""
        if plan_id not in self.active_plans:
            return {"success": False, "error": "Plan not found"}

        plan = self.active_plans[plan_id]
        plan.started_at = time.time()

        try:
            # Get execution levels (tasks that can run in parallel)
            levels = self._topological_sort(plan.subtasks)
            task_map = {t.task_id: t for t in plan.subtasks}

            logger.info(f"Executing plan {plan_id} in {len(levels)} levels")

            # Execute level by level
            for level_num, level in enumerate(levels, 1):
                logger.info(f"Level {level_num}: Executing {len(level)} tasks in parallel")

                # Execute all tasks in this level in parallel
                tasks_to_run = [task_map[tid] for tid in level]
                await self._execute_level(tasks_to_run, plan, executor)

                # Notify progress
                await self._notify_progress(plan, level_num, len(levels))

                # Check if any task failed
                failed = [t for t in tasks_to_run if t.state == TaskState.FAILED]
                if failed:
                    logger.error(f"Level {level_num} failed, rolling back")
                    await self._rollback_plan(plan)
                    return {
                        "success": False,
                        "error": f"Tasks failed: {[t.name for t in failed]}",
                        "plan_id": plan_id
                    }

            plan.completed_at = time.time()
            plan.total_duration = plan.completed_at - plan.started_at
            plan.success = True

            # Move to history
            self.plan_history.append(plan)
            del self.active_plans[plan_id]

            logger.info(f"Plan {plan_id} completed successfully in {plan.total_duration:.2f}s")

            return {
                "success": True,
                "plan_id": plan_id,
                "duration": plan.total_duration,
                "completed_tasks": len(plan.subtasks),
                "results": plan.context.results
            }

        except Exception as e:
            logger.error(f"Plan execution error: {e}")
            await self._rollback_plan(plan)
            return {"success": False, "error": str(e)}

    async def _execute_level(
        self,
        tasks: List[SubTask],
        plan: ExecutionPlan,
        executor
    ):
        """Execute all tasks in a level in parallel"""
        async def run_task(task: SubTask):
            task.state = TaskState.RUNNING
            task.started_at = time.time()

            try:
                # Execute the task
                if executor:
                    from tools import AVAILABLE_TOOLS
                    tool = AVAILABLE_TOOLS.get(task.action)

                    if tool:
                        result = await executor.execute(tool, task.params)
                        task.result = result

                        if result.get("success"):
                            task.state = TaskState.COMPLETED
                            plan.context.results[task.task_id] = result
                        else:
                            raise Exception(result.get("error", "Unknown error"))
                    else:
                        raise Exception(f"Tool not found: {task.action}")
                else:
                    # Simulation mode
                    await asyncio.sleep(0.1)
                    task.state = TaskState.COMPLETED
                    task.result = {"success": True, "simulated": True}

                task.completed_at = time.time()
                logger.info(f"Task {task.name} completed")

            except Exception as e:
                task.state = TaskState.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                logger.error(f"Task {task.name} failed: {e}")

                # Retry if possible
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    logger.info(f"Retrying task {task.name} ({task.retry_count}/{task.max_retries})")
                    await asyncio.sleep(1)  # Backoff
                    await run_task(task)

        # Run all tasks in parallel with semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.executor_pool_size)

        async def limited_run(task):
            async with semaphore:
                await run_task(task)

        await asyncio.gather(*[limited_run(task) for task in tasks])

    async def _rollback_plan(self, plan: ExecutionPlan):
        """Rollback completed tasks in reverse order"""
        logger.warning(f"Rolling back plan {plan.plan_id}")

        # Reverse order rollback
        for task in reversed(plan.subtasks):
            if task.state == TaskState.COMPLETED and task.rollback_action:
                try:
                    await task.rollback_action()
                    task.state = TaskState.ROLLED_BACK
                    logger.info(f"Rolled back task {task.name}")
                except Exception as e:
                    logger.error(f"Rollback failed for {task.name}: {e}")

    async def _notify_progress(self, plan: ExecutionPlan, current_level: int, total_levels: int):
        """Notify progress callbacks"""
        progress = (current_level / total_levels) * 100

        for callback in self.progress_callbacks:
            try:
                await callback({
                    "plan_id": plan.plan_id,
                    "progress": progress,
                    "current_level": current_level,
                    "total_levels": total_levels,
                    "completed_tasks": sum(1 for t in plan.subtasks if t.state == TaskState.COMPLETED),
                    "total_tasks": len(plan.subtasks)
                })
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    def get_plan_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a plan"""
        plan = self.active_plans.get(plan_id)
        if not plan:
            # Check history
            for p in self.plan_history:
                if p.plan_id == plan_id:
                    plan = p
                    break

        if not plan:
            return None

        completed = sum(1 for t in plan.subtasks if t.state == TaskState.COMPLETED)
        failed = sum(1 for t in plan.subtasks if t.state == TaskState.FAILED)
        running = sum(1 for t in plan.subtasks if t.state == TaskState.RUNNING)

        return {
            "plan_id": plan.plan_id,
            "description": plan.description,
            "total_tasks": len(plan.subtasks),
            "completed": completed,
            "failed": failed,
            "running": running,
            "success": plan.success,
            "duration": plan.total_duration if plan.completed_at else time.time() - (plan.started_at or time.time()),
            "tasks": [
                {
                    "id": t.task_id,
                    "name": t.name,
                    "state": t.state.value,
                    "retry_count": t.retry_count
                }
                for t in plan.subtasks
            ]
        }

    def cancel_plan(self, plan_id: str):
        """Cancel an active plan"""
        if plan_id in self.active_plans:
            plan = self.active_plans[plan_id]
            for task in plan.subtasks:
                if task.state in [TaskState.PENDING, TaskState.READY, TaskState.RUNNING]:
                    task.state = TaskState.CANCELLED
            logger.info(f"Plan {plan_id} cancelled")
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        """Get planner summary"""
        return {
            "active_plans": len(self.active_plans),
            "completed_plans": len(self.plan_history),
            "total_tasks_executed": sum(len(p.subtasks) for p in self.plan_history),
            "average_plan_duration": sum(p.total_duration for p in self.plan_history) / len(self.plan_history) if self.plan_history else 0
        }


# Global instance
_intelligent_planner: Optional[IntelligentPlanner] = None


def get_intelligent_planner() -> IntelligentPlanner:
    """Get or create global intelligent planner instance"""
    global _intelligent_planner
    if _intelligent_planner is None:
        _intelligent_planner = IntelligentPlanner()
    return _intelligent_planner
