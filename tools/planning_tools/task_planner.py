"""
Görev Planlayıcı - Task Planner
Karmaşık, bağımlılıklı görev orkestrasyonu ve yürütme
"""

import asyncio
import uuid
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable
from utils.logger import get_logger

logger = get_logger("task_planner")


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PlanStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DEPENDENCY = "dependency"


@dataclass
class Task:
    """Tek bir görev tanımı"""
    id: str
    name: str
    action: str
    params: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "params": self.params,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }


@dataclass
class Plan:
    """Görev planı"""
    id: str
    name: str
    description: str
    tasks: list[Task]
    execution_mode: ExecutionMode
    status: PlanStatus = PlanStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    current_task_index: int = 0
    results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tasks": [t.to_dict() for t in self.tasks],
            "execution_mode": self.execution_mode.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "current_task_index": self.current_task_index,
            "progress": self._calculate_progress()
        }

    def _calculate_progress(self) -> int:
        if not self.tasks:
            return 0
        completed = sum(1 for t in self.tasks if t.status in [TaskStatus.COMPLETED, TaskStatus.SKIPPED])
        return int((completed / len(self.tasks)) * 100)


class TaskPlanner:
    """Görev planlama ve orkestrasyon yöneticisi"""

    _instance = None
    _plans: dict[str, Plan] = {}
    _tool_executor: Callable | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._plans = {}
            cls._tool_executor = None
        return cls._instance

    @classmethod
    def set_tool_executor(cls, executor: Callable):
        """Tool çalıştırıcı fonksiyonunu ayarla"""
        cls._tool_executor = executor

    @classmethod
    def get_plans(cls) -> dict[str, Plan]:
        """Tüm planları döndür"""
        return cls._plans

    async def create_plan(
        self,
        name: str,
        description: str,
        tasks: list[dict],
        execution_mode: str = "sequential"
    ) -> dict[str, Any]:
        """
        Yeni görev planı oluştur

        Args:
            name: Plan adı
            description: Plan açıklaması
            tasks: Görev listesi
                Her görev: {"name": str, "action": str, "params": dict, "depends_on": list[str]}
            execution_mode: Yürütme modu (sequential, parallel, dependency)

        Returns:
            dict: Oluşturulan plan bilgileri
        """
        try:
            plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

            # Parse execution mode
            try:
                mode = ExecutionMode(execution_mode.lower())
            except ValueError:
                mode = ExecutionMode.SEQUENTIAL

            # Create tasks
            plan_tasks = []
            for i, task_def in enumerate(tasks):
                task_id = task_def.get("id", f"task_{i+1}")
                task = Task(
                    id=task_id,
                    name=task_def.get("name", f"Görev {i+1}"),
                    action=task_def.get("action", ""),
                    params=task_def.get("params", {}),
                    depends_on=task_def.get("depends_on", [])
                )
                plan_tasks.append(task)

            plan = Plan(
                id=plan_id,
                name=name,
                description=description,
                tasks=plan_tasks,
                execution_mode=mode
            )

            self._plans[plan_id] = plan

            logger.info(f"Plan oluşturuldu: {name} ({plan_id}) - {len(plan_tasks)} görev")

            return {
                "success": True,
                "plan_id": plan_id,
                "name": name,
                "task_count": len(plan_tasks),
                "execution_mode": mode.value,
                "message": f"Plan oluşturuldu: {name} ({len(plan_tasks)} görev)"
            }

        except Exception as e:
            logger.error(f"Plan oluşturma hatası: {e}")
            return {"success": False, "error": f"Plan oluşturulamadı: {str(e)}"}

    async def execute_plan(
        self,
        plan_id: str,
        on_progress: Callable[[str, int, str], None] | None = None
    ) -> dict[str, Any]:
        """
        Planı yürüt

        Args:
            plan_id: Plan ID'si
            on_progress: İlerleme callback fonksiyonu (task_id, progress, message)

        Returns:
            dict: Yürütme sonucu
        """
        try:
            if plan_id not in self._plans:
                return {"success": False, "error": f"Plan bulunamadı: {plan_id}"}

            plan = self._plans[plan_id]

            if plan.status == PlanStatus.RUNNING:
                return {"success": False, "error": "Plan zaten çalışıyor"}

            if plan.status in [PlanStatus.COMPLETED, PlanStatus.CANCELLED]:
                return {"success": False, "error": f"Plan durumu: {plan.status.value}"}

            plan.status = PlanStatus.RUNNING
            plan.started_at = datetime.now().isoformat()

            logger.info(f"Plan yürütülüyor: {plan.name} ({plan_id})")

            try:
                if plan.execution_mode == ExecutionMode.PARALLEL:
                    await self._execute_parallel(plan, on_progress)
                elif plan.execution_mode == ExecutionMode.DEPENDENCY:
                    await self._execute_with_dependencies(plan, on_progress)
                else:
                    await self._execute_sequential(plan, on_progress)

                # Determine final status
                failed_tasks = [t for t in plan.tasks if t.status == TaskStatus.FAILED]
                completed_tasks = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED]

                if len(completed_tasks) == len(plan.tasks):
                    plan.status = PlanStatus.COMPLETED
                elif failed_tasks and completed_tasks:
                    plan.status = PlanStatus.PARTIAL
                elif failed_tasks:
                    plan.status = PlanStatus.FAILED
                else:
                    plan.status = PlanStatus.COMPLETED

                plan.completed_at = datetime.now().isoformat()

                logger.info(f"Plan tamamlandı: {plan.name} - {plan.status.value}")

                return {
                    "success": True,
                    "plan_id": plan_id,
                    "status": plan.status.value,
                    "completed_tasks": len(completed_tasks),
                    "failed_tasks": len(failed_tasks),
                    "total_tasks": len(plan.tasks),
                    "results": plan.results,
                    "message": f"Plan tamamlandı: {len(completed_tasks)}/{len(plan.tasks)} görev başarılı"
                }

            except asyncio.CancelledError:
                plan.status = PlanStatus.CANCELLED
                plan.completed_at = datetime.now().isoformat()
                return {
                    "success": False,
                    "plan_id": plan_id,
                    "status": "cancelled",
                    "message": "Plan iptal edildi"
                }

        except Exception as e:
            logger.error(f"Plan yürütme hatası: {e}")
            if plan_id in self._plans:
                self._plans[plan_id].status = PlanStatus.FAILED
            return {"success": False, "error": f"Plan yürütülemedi: {str(e)}"}

    async def _execute_sequential(
        self,
        plan: Plan,
        on_progress: Callable | None
    ):
        """Görevleri sırayla yürüt"""
        for i, task in enumerate(plan.tasks):
            plan.current_task_index = i

            if on_progress:
                progress = int((i / len(plan.tasks)) * 100)
                on_progress(task.id, progress, f"Çalışıyor: {task.name}")

            await self._execute_task(task, plan)

            if task.status == TaskStatus.FAILED:
                # Check if we should continue on failure
                logger.warning(f"Görev başarısız: {task.name} - devam ediliyor")

    async def _execute_parallel(
        self,
        plan: Plan,
        on_progress: Callable | None
    ):
        """Görevleri paralel yürüt"""
        async def run_task(task: Task, index: int):
            if on_progress:
                on_progress(task.id, 0, f"Başlatılıyor: {task.name}")
            await self._execute_task(task, plan)
            if on_progress:
                progress = int(((index + 1) / len(plan.tasks)) * 100)
                on_progress(task.id, progress, f"Tamamlandı: {task.name}")

        await asyncio.gather(*[
            run_task(task, i) for i, task in enumerate(plan.tasks)
        ], return_exceptions=True)

    async def _execute_with_dependencies(
        self,
        plan: Plan,
        on_progress: Callable | None
    ):
        """Bağımlılıklara göre görevleri yürüt"""
        completed_ids = set()
        pending_tasks = list(plan.tasks)

        while pending_tasks:
            # Find tasks with satisfied dependencies
            ready_tasks = [
                t for t in pending_tasks
                if all(dep in completed_ids for dep in t.depends_on)
            ]

            if not ready_tasks:
                # Deadlock or circular dependency
                for t in pending_tasks:
                    t.status = TaskStatus.SKIPPED
                    t.error = "Bağımlılık çözülemedi"
                break

            # Execute ready tasks in parallel
            for task in ready_tasks:
                if on_progress:
                    progress = int((len(completed_ids) / len(plan.tasks)) * 100)
                    on_progress(task.id, progress, f"Çalışıyor: {task.name}")

                await self._execute_task(task, plan)
                completed_ids.add(task.id)
                pending_tasks.remove(task)

    async def _execute_task(self, task: Task, plan: Plan):
        """Tek bir görevi yürüt"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()

        try:
            # Resolve variable references ($task_id.result)
            resolved_params = self._resolve_params(task.params, plan)

            # Execute the task
            if self._tool_executor:
                result = await self._tool_executor(task.action, resolved_params)
            else:
                # Fallback - import and use tools directly (import here to avoid circular import)
                from tools import AVAILABLE_TOOLS
                tool_func = AVAILABLE_TOOLS.get(task.action)
                if tool_func:
                    result = await tool_func(**resolved_params)
                else:
                    result = {"success": False, "error": f"Bilinmeyen action: {task.action}"}

            task.result = result
            plan.results[task.id] = result

            if result.get("success"):
                task.status = TaskStatus.COMPLETED
                logger.info(f"Görev tamamlandı: {task.name}")
            else:
                task.status = TaskStatus.FAILED
                task.error = result.get("error", "Bilinmeyen hata")
                logger.warning(f"Görev başarısız: {task.name} - {task.error}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.result = {"success": False, "error": str(e)}
            plan.results[task.id] = task.result
            logger.error(f"Görev hatası: {task.name} - {e}")

        task.completed_at = datetime.now().isoformat()

    def _resolve_params(self, params: dict, plan: Plan) -> dict:
        """Parametre içindeki değişken referanslarını çöz"""
        resolved = {}

        for key, value in params.items():
            if isinstance(value, str) and value.startswith("$"):
                # Variable reference: $task_id.result or $task_id.result.field
                resolved[key] = self._resolve_variable(value, plan)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_params(value, plan)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_variable(v, plan) if isinstance(v, str) and v.startswith("$") else v
                    for v in value
                ]
            else:
                resolved[key] = value

        return resolved

    def _resolve_variable(self, var_ref: str, plan: Plan) -> Any:
        """Değişken referansını çöz"""
        # Format: $task_id.result.field1.field2
        match = re.match(r'\$(\w+)\.(\w+)(?:\.(.+))?', var_ref)
        if not match:
            return var_ref

        task_id = match.group(1)
        base_field = match.group(2)
        sub_fields = match.group(3)

        if task_id not in plan.results:
            logger.warning(f"Referans bulunamadı: {var_ref}")
            return var_ref

        result = plan.results[task_id]

        # Get base field (usually "result")
        if base_field == "result":
            value = result
        else:
            value = result.get(base_field, var_ref)

        # Navigate sub-fields
        if sub_fields and isinstance(value, dict):
            for field in sub_fields.split("."):
                if isinstance(value, dict):
                    value = value.get(field, var_ref)
                else:
                    break

        return value

    async def get_plan_status(self, plan_id: str) -> dict[str, Any]:
        """Plan durumunu getir"""
        if plan_id not in self._plans:
            return {"success": False, "error": f"Plan bulunamadı: {plan_id}"}

        plan = self._plans[plan_id]
        return {
            "success": True,
            **plan.to_dict()
        }

    async def cancel_plan(self, plan_id: str) -> dict[str, Any]:
        """Planı iptal et"""
        if plan_id not in self._plans:
            return {"success": False, "error": f"Plan bulunamadı: {plan_id}"}

        plan = self._plans[plan_id]

        if plan.status != PlanStatus.RUNNING:
            return {"success": False, "error": f"Plan çalışmıyor: {plan.status.value}"}

        plan.status = PlanStatus.CANCELLED
        plan.completed_at = datetime.now().isoformat()

        # Mark pending tasks as cancelled
        for task in plan.tasks:
            if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                task.status = TaskStatus.CANCELLED

        logger.info(f"Plan iptal edildi: {plan.name}")

        return {
            "success": True,
            "plan_id": plan_id,
            "status": "cancelled",
            "message": f"Plan iptal edildi: {plan.name}"
        }

    async def list_plans(self, include_completed: bool = False) -> dict[str, Any]:
        """Planları listele"""
        plans = []
        for plan in self._plans.values():
            if not include_completed and plan.status in [PlanStatus.COMPLETED, PlanStatus.CANCELLED]:
                continue
            plans.append({
                "id": plan.id,
                "name": plan.name,
                "status": plan.status.value,
                "task_count": len(plan.tasks),
                "progress": plan._calculate_progress(),
                "created_at": plan.created_at
            })

        return {
            "success": True,
            "plans": plans,
            "count": len(plans)
        }


# Global instance
_planner = TaskPlanner()


async def create_plan(
    name: str,
    description: str,
    tasks: list[dict],
    execution_mode: str = "sequential"
) -> dict[str, Any]:
    """Wrapper function for TaskPlanner.create_plan"""
    return await _planner.create_plan(name, description, tasks, execution_mode)


async def execute_plan(
    plan_id: str,
    on_progress: Callable | None = None
) -> dict[str, Any]:
    """Wrapper function for TaskPlanner.execute_plan"""
    return await _planner.execute_plan(plan_id, on_progress)


async def get_plan_status(plan_id: str) -> dict[str, Any]:
    """Wrapper function for TaskPlanner.get_plan_status"""
    return await _planner.get_plan_status(plan_id)


async def cancel_plan(plan_id: str) -> dict[str, Any]:
    """Wrapper function for TaskPlanner.cancel_plan"""
    return await _planner.cancel_plan(plan_id)


async def list_plans(include_completed: bool = False) -> dict[str, Any]:
    """Wrapper function for TaskPlanner.list_plans"""
    return await _planner.list_plans(include_completed)
