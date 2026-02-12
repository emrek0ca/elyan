"""
Intelligent Plan Executor

Executes execution plans with:
- Progress monitoring
- Error handling and recovery
- Pause/resume capability
- Parallel execution where safe
- Real-time status updates
"""

import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from .planner import ExecutionPlan, Task, TaskStatus
from .task_executor import TaskExecutor
from utils.logger import get_logger

logger = get_logger("executor")


class PlanExecutor:
    """
    Executes execution plans created by the Planner
    
    Features:
    - Sequential and parallel execution
    - Progress callbacks
    - Error recovery
    - Execution monitoring
    """
    
    def __init__(self, task_executor: TaskExecutor):
        self.task_executor = task_executor
        self.current_plan: Optional[ExecutionPlan] = None
        self.is_paused = False
        self.progress_callback: Optional[Callable] = None
    
    async def execute_plan(self, plan: ExecutionPlan, 
                          progress_callback: Callable = None,
                          user_id: int = None) -> Dict[str, Any]:
        """
        Execute an execution plan
        
        Args:
            plan: The ExecutionPlan to execute
            progress_callback: Optional callback for progress updates
            user_id: User ID for memory/history
        
        Returns:
            Execution result with outcomes
        """
        logger.info(f"Executing plan for goal: {plan.goal}")
        self.current_plan = plan
        self.progress_callback = progress_callback
        
        plan.status = "executing"
        start_time = datetime.now()
        
        results = []
        errors = []
        
        try:
            # Execute tasks in dependency order
            while not plan.is_complete():
                if self.is_paused:
                    logger.info("Execution paused")
                    await asyncio.sleep(1)
                    continue
                
                # Get tasks ready to execute
                ready_tasks = plan.get_ready_tasks()
                
                if not ready_tasks:
                    # No ready tasks but plan not complete = deadlock
                    logger.error("Execution deadlock detected")
                    break
                
                # Execute ready tasks
                for task in ready_tasks:
                    task.status = TaskStatus.RUNNING
                    
                    # Send progress update
                    if self.progress_callback:
                        await self.progress_callback(plan.get_progress())
                    
                    # Execute the task
                    task_start = datetime.now()
                    result = await self._execute_task(task)
                    task_end = datetime.now()
                    
                    task.actual_duration = (task_end - task_start).total_seconds()
                    task.result = result
                    
                    if result.get("success", False):
                        task.status = TaskStatus.COMPLETED
                        results.append({
                            "task_id": task.id,
                            "task_name": task.name,
                            "result": result
                        })
                        logger.info(f"Task '{task.name}' completed successfully")
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = result.get("error", "Unknown error")
                        errors.append({
                            "task_id": task.id,
                            "task_name": task.name,
                            "error": task.error
                        })
                        logger.error(f"Task '{task.name}' failed: {task.error}")
                        
                        # Decide whether to continue or stop
                        if not await self._should_continue_after_failure(task, plan):
                            logger.info("Stopping execution due to critical failure")
                            break
            
            end_time = datetime.now()
            total_duration = (end_time - start_time).total_seconds()
            
            # Final progress update
            if self.progress_callback:
                await self.progress_callback(plan.get_progress())
            
            plan.status = "completed" if len(errors) == 0 else "partial"
            
            return {
                "success": len(errors) == 0,
                "plan_goal": plan.goal,
                "total_tasks": len(plan.tasks),
                "completed_tasks": sum(1 for t in plan.tasks if t.status == TaskStatus.COMPLETED),
                "failed_tasks": len(errors),
                "results": results,
                "errors": errors,
                "duration": total_duration,
                "estimated_duration": plan.total_estimated_time
            }
        
        except Exception as e:
            logger.error(f"Plan execution error: {e}")
            plan.status = "failed"
            return {
                "success": False,
                "error": str(e),
                "results": results,
                "errors": errors
            }
    
    async def _execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a single task"""
        try:
            logger.info(f"Executing task: {task.name} (action: {task.action})")
            
            # Use the task executor to run the tool
            result = await self.task_executor.execute(task.action, **task.params)
            
            return result
        
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _should_continue_after_failure(self, failed_task: Task, plan: ExecutionPlan) -> bool:
        """
        Decide whether to continue execution after a task failure
        
        Consider:
        - Criticality of the failed task
        - Whether other tasks depend on it
        - User preferences
        """
        # Check if any remaining tasks depend on the failed task
        dependent_tasks = [
            t for t in plan.tasks
            if failed_task.id in t.depends_on and t.status == TaskStatus.PENDING
        ]
        
        if dependent_tasks:
            # Mark dependent tasks as skipped
            for task in dependent_tasks:
                task.status = TaskStatus.SKIPPED
                logger.info(f"Skipping task '{task.name}' due to failed dependency")
        
        # Continue with other independent tasks
        return True
    
    def pause(self):
        """Pause execution"""
        self.is_paused = True
        logger.info("Execution paused")
    
    def resume(self):
        """Resume execution"""
        self.is_paused = False
        logger.info("Execution resumed")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current execution status"""
        if not self.current_plan:
            return {"status": "idle"}
        
        return {
            "status": self.current_plan.status,
            "is_paused": self.is_paused,
            "progress": self.current_plan.get_progress(),
            "goal": self.current_plan.goal
        }
