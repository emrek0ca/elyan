"""
Advanced Automation Engine
Zamanlanmış görevler, workflow chains, conditional automation
"""

import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import schedule

from utils.logger import get_logger

logger = get_logger("automation_engine")


class TriggerType(Enum):
    """Automation trigger types"""
    SCHEDULED = "scheduled"  # Time-based (cron-like)
    EVENT = "event"  # Event-based (after X happens)
    CONDITIONAL = "conditional"  # Condition-based (when X is true)
    RECURRING = "recurring"  # Recurring (every X minutes/hours)
    CHAIN = "chain"  # Chained (after task A, do task B)


class TaskStatus(Enum):
    """Automation task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


@dataclass
class AutomationTask:
    """Represents an automated task"""
    task_id: str
    name: str
    trigger_type: TriggerType
    action: str  # Tool name to execute
    params: Dict[str, Any]
    schedule_config: Optional[Dict[str, Any]] = None  # Cron-like config
    condition: Optional[str] = None  # Python expression for conditional
    chain_after: Optional[str] = None  # Task ID to chain after
    enabled: bool = True
    status: TaskStatus = TaskStatus.PENDING
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()


class AutomationEngine:
    """
    Advanced Automation Engine
    - Schedule tasks (daily, weekly, custom cron)
    - Chain workflows (A → B → C)
    - Conditional execution
    - Recurring tasks
    """

    def __init__(self):
        self.tasks: Dict[str, AutomationTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.task_results: Dict[str, Any] = {}
        self.event_callbacks: Dict[str, List[Callable]] = {}
        self._scheduler_running = False

        logger.info("Automation Engine initialized")

    def create_task(
        self,
        name: str,
        action: str,
        params: Dict[str, Any],
        trigger_type: TriggerType = TriggerType.SCHEDULED,
        schedule_config: Optional[Dict[str, Any]] = None,
        condition: Optional[str] = None,
        chain_after: Optional[str] = None
    ) -> str:
        """Create a new automation task"""
        import uuid
        task_id = str(uuid.uuid4())[:8]

        task = AutomationTask(
            task_id=task_id,
            name=name,
            trigger_type=trigger_type,
            action=action,
            params=params,
            schedule_config=schedule_config,
            condition=condition,
            chain_after=chain_after,
            status=TaskStatus.SCHEDULED if trigger_type == TriggerType.SCHEDULED else TaskStatus.PENDING
        )

        self.tasks[task_id] = task

        # Calculate next run for scheduled tasks
        if trigger_type == TriggerType.SCHEDULED and schedule_config:
            task.next_run = self._calculate_next_run(schedule_config)

        logger.info(f"Created automation task: {name} ({task_id})")
        return task_id

    def _calculate_next_run(self, schedule_config: Dict[str, Any]) -> float:
        """Calculate next run time from schedule config"""
        now = datetime.now()

        # Daily schedule
        if schedule_config.get("type") == "daily":
            hour = schedule_config.get("hour", 9)
            minute = schedule_config.get("minute", 0)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If time has passed today, schedule for tomorrow
            if next_run <= now:
                next_run += timedelta(days=1)

            return next_run.timestamp()

        # Recurring schedule (every X minutes/hours)
        elif schedule_config.get("type") == "recurring":
            interval = schedule_config.get("interval", 60)  # minutes
            return time.time() + (interval * 60)

        # Weekly schedule
        elif schedule_config.get("type") == "weekly":
            day_of_week = schedule_config.get("day_of_week", 0)  # 0 = Monday
            hour = schedule_config.get("hour", 9)
            minute = schedule_config.get("minute", 0)

            days_ahead = day_of_week - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7

            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)

            return next_run.timestamp()

        # Default: 1 hour from now
        return time.time() + 3600

    async def execute_task(self, task_id: str, executor=None) -> Dict[str, Any]:
        """Execute an automation task"""
        if task_id not in self.tasks:
            return {"success": False, "error": "Task not found"}

        task = self.tasks[task_id]

        if not task.enabled:
            return {"success": False, "error": "Task is disabled"}

        # Check condition if exists
        if task.condition:
            try:
                condition_met = eval(task.condition, {"time": time, "datetime": datetime})
                if not condition_met:
                    logger.info(f"Task {task_id} condition not met: {task.condition}")
                    return {"success": False, "error": "Condition not met"}
            except Exception as e:
                logger.error(f"Error evaluating condition: {e}")
                return {"success": False, "error": f"Invalid condition: {e}"}

        task.status = TaskStatus.RUNNING
        task.run_count += 1
        task.last_run = time.time()

        logger.info(f"Executing automation task: {task.name} ({task_id})")

        try:
            # Execute the action
            if executor:
                from tools import AVAILABLE_TOOLS
                tool_func = AVAILABLE_TOOLS.get(task.action)

                if not tool_func:
                    raise ValueError(f"Tool not found: {task.action}")

                result = await executor.execute(tool_func, task.params)

                if result.get("success"):
                    task.status = TaskStatus.COMPLETED
                    task.success_count += 1
                else:
                    task.status = TaskStatus.FAILED
                    task.failure_count += 1

                # Store result
                self.task_results[task_id] = result

                # Update next run for recurring tasks
                if task.trigger_type == TriggerType.RECURRING and task.schedule_config:
                    task.next_run = self._calculate_next_run(task.schedule_config)
                    task.status = TaskStatus.SCHEDULED
                elif task.trigger_type == TriggerType.SCHEDULED and task.schedule_config:
                    task.next_run = self._calculate_next_run(task.schedule_config)
                    task.status = TaskStatus.SCHEDULED

                return result
            else:
                task.status = TaskStatus.FAILED
                return {"success": False, "error": "No executor provided"}

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            task.status = TaskStatus.FAILED
            task.failure_count += 1
            return {"success": False, "error": str(e)}

    async def start_scheduler(self, executor=None):
        """Start the automation scheduler"""
        self._scheduler_running = True
        logger.info("Automation scheduler started")

        while self._scheduler_running:
            try:
                now = time.time()

                # Check all scheduled tasks
                for task_id, task in list(self.tasks.items()):
                    if not task.enabled:
                        continue

                    # Execute scheduled tasks that are due
                    if task.status == TaskStatus.SCHEDULED and task.next_run:
                        if now >= task.next_run:
                            logger.info(f"Triggering scheduled task: {task.name}")
                            await self.execute_task(task_id, executor)

                    # Execute chained tasks
                    if task.trigger_type == TriggerType.CHAIN and task.chain_after:
                        parent_task = self.tasks.get(task.chain_after)
                        if parent_task and parent_task.status == TaskStatus.COMPLETED:
                            logger.info(f"Triggering chained task: {task.name}")
                            await self.execute_task(task_id, executor)

                # Sleep for 10 seconds between checks
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(10)

    def stop_scheduler(self):
        """Stop the automation scheduler"""
        self._scheduler_running = False
        logger.info("Automation scheduler stopped")

    def enable_task(self, task_id: str):
        """Enable an automation task"""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = True
            logger.info(f"Task enabled: {task_id}")

    def disable_task(self, task_id: str):
        """Disable an automation task"""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = False
            logger.info(f"Task disabled: {task_id}")

    def delete_task(self, task_id: str):
        """Delete an automation task"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            logger.info(f"Task deleted: {task_id}")

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task status and info"""
        if task_id not in self.tasks:
            return None

        task = self.tasks[task_id]
        result = self.task_results.get(task_id)

        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "trigger_type": task.trigger_type.value,
            "action": task.action,
            "enabled": task.enabled,
            "run_count": task.run_count,
            "success_count": task.success_count,
            "failure_count": task.failure_count,
            "last_run": datetime.fromtimestamp(task.last_run).strftime("%Y-%m-%d %H:%M:%S") if task.last_run else None,
            "next_run": datetime.fromtimestamp(task.next_run).strftime("%Y-%m-%d %H:%M:%S") if task.next_run else None,
            "last_result": result
        }

    def list_tasks(self, filter_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all automation tasks"""
        tasks = []
        for task_id, task in self.tasks.items():
            if filter_by and task.status.value != filter_by:
                continue

            tasks.append(self.get_task_status(task_id))

        return tasks

    def get_summary(self) -> Dict[str, Any]:
        """Get automation engine summary"""
        total = len(self.tasks)
        enabled = sum(1 for t in self.tasks.values() if t.enabled)
        scheduled = sum(1 for t in self.tasks.values() if t.status == TaskStatus.SCHEDULED)
        running = sum(1 for t in self.tasks.values() if t.status == TaskStatus.RUNNING)

        return {
            "total_tasks": total,
            "enabled_tasks": enabled,
            "scheduled_tasks": scheduled,
            "running_tasks": running,
            "scheduler_active": self._scheduler_running
        }


# Global instance
_automation_engine: Optional[AutomationEngine] = None


def get_automation_engine() -> AutomationEngine:
    """Get or create global automation engine instance"""
    global _automation_engine
    if _automation_engine is None:
        _automation_engine = AutomationEngine()
    return _automation_engine
