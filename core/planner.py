"""
Autonomous Task Planner

Creates execution plans from complex goals by:
- Decomposing goals into sub-tasks
- Building dependency graphs
- Estimating resources and time
- Generating contingency plans
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from utils.logger import get_logger

logger = get_logger("planner")


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """Represents a single task in an execution plan"""
    id: str
    name: str
    action: str
    params: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    estimated_duration: float = 0.0
    actual_duration: float = 0.0


@dataclass
class ExecutionPlan:
    """Represents a complete execution plan"""
    goal: str
    tasks: List[Task]
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "created"
    created_at: str = ""
    total_estimated_time: float = 0.0
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to execute (all dependencies met)"""
        ready = []
        for task in self.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            
            # Check if all dependencies are completed
            all_deps_met = True
            for dep_id in task.depends_on:
                dep_task = self.get_task(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    all_deps_met = False
                    break
            
            if all_deps_met:
                ready.append(task)
        
        return ready
    
    def is_complete(self) -> bool:
        """Check if all tasks are completed or failed"""
        for task in self.tasks:
            if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                return False
        return True
    
    def get_progress(self) -> Dict[str, Any]:
        """Get plan execution progress"""
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        
        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "pending": total - completed - failed,
            "progress_percent": (completed / total * 100) if total > 0 else 0
        }


class AutonomousPlanner:
    """
    Autonomous task planner that creates execution plans from goals
    
    Uses LLM to:
    - Understand complex goals
    - Break down into sub-tasks
    - Determine dependencies
    - Estimate resources
    """
    
    def __init__(self, llm_client, reasoning_engine):
        self.llm = llm_client
        self.reasoning = reasoning_engine
        self.max_tasks_per_plan = 20
    
    async def create_plan(self, goal: str, context: Dict[str, Any] = None) -> ExecutionPlan:
        """
        Create an execution plan for a goal
        
        Args:
            goal: The user's goal
            context: Additional context (user preferences, history, etc.)
        
        Returns:
            ExecutionPlan with tasks and dependencies
        """
        logger.info(f"Creating plan for goal: {goal}")
        
        # Use Chain-of-Thought reasoning to plan
        reasoning_result = await self.reasoning.cot.reason(goal, context)
        
        # Extract recommended actions from reasoning
        recommended_actions = reasoning_result.get("recommended_actions", [])
        
        if not recommended_actions:
            # Fallback: ask LLM directly for a plan
            recommended_actions = await self._ask_llm_for_plan(goal, context)
        
        # Build execution plan from actions
        plan = await self._build_execution_plan(goal, recommended_actions, reasoning_result)
        
        logger.info(f"Created plan with {len(plan.tasks)} tasks")
        return plan
    
    async def _ask_llm_for_plan(self, goal: str, context: Dict[str, Any] = None) -> List[Dict]:
        """Ask LLM to create a task decomposition"""
        
        prompt = f"""You are a Strategic Chief of Staff. Your objective: {goal}
        
        Plan with extreme competence and precision. Focus on:
        1. STRATEGIC PHASES: Break the mission into logical execution phases.
        2. DEPENDENCIES: Ensure all prerequisites are clearly mapped.
        3. DATA PIPING: Use placeholders like "{{{{last_file}}}}" or "{{{{step1_result}}}}" to pass data between steps.
        4. CONTINGENCY: Account for potential failures in the roadmap.

Respond with a JSON array of tasks:
[
    {{
        "id": "task_1",
        "name": "Descriptive task name",
        "action": "tool_name",
        "params": {{"param1": "value1"}},
        "depends_on": [],
        "estimated_duration": 5.0
    }},
    ...
]

IMPORTANT RULES:
- Each task must use a valid action from available tools
- Use depends_on to specify task dependencies by ID
- Keep the plan focused and achievable
- Maximum {self.max_tasks_per_plan} tasks
"""
        
        if context:
            import json
            prompt += f"\n\nADDITIONAL CONTEXT:\n{json.dumps(context, indent=2)}\n"
        
        response = await self.llm._ask_llm_with_custom_prompt(prompt, temperature=0.3)
        
        # Parse the response
        try:
            import re
            import json
            
            # Extract JSON array
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                actions = json.loads(json_match.group())
                return actions if isinstance(actions, list) else []
        except Exception as e:
            logger.error(f"Error parsing plan from LLM: {e}")
        
        return []
    
    async def _build_execution_plan(self, goal: str, actions: List[Dict], 
                                   reasoning_result: Dict) -> ExecutionPlan:
        """Build ExecutionPlan from actions"""
        from datetime import datetime
        
        tasks = []
        total_time = 0.0
        
        for i, action_dict in enumerate(actions):
            task = Task(
                id=action_dict.get("id", f"task_{i+1}"),
                name=action_dict.get("name", f"Task {i+1}"),
                action=action_dict.get("action", "unknown"),
                params=action_dict.get("params", {}),
                depends_on=action_dict.get("depends_on", []),
                estimated_duration=action_dict.get("estimated_duration", 5.0)
            )
            tasks.append(task)
            total_time += task.estimated_duration
        
        plan = ExecutionPlan(
            goal=goal,
            tasks=tasks,
            metadata={
                "reasoning_steps": reasoning_result.get("reasoning_steps", []),
                "confidence": reasoning_result.get("confidence", 0.0)
            },
            created_at=datetime.now().isoformat(),
            total_estimated_time=total_time
        )
        
        return plan
    
    async def validate_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """
        Validate that a plan is executable
        
        Checks:
        - All actions are valid
        - Dependencies are resolvable
        - No circular dependencies
        - Resource requirements are reasonable
        """
        issues = []
        warnings = []
        
        # Check for circular dependencies
        if self._has_circular_dependencies(plan):
            issues.append("Plan contains circular dependencies")
        
        # Check action validity
        from tools import AVAILABLE_TOOLS
        for task in plan.tasks:
            if task.action not in AVAILABLE_TOOLS and task.action != "multi_task" and task.action != "chat":
                warnings.append(f"Task '{task.name}' uses unknown action: {task.action}")
        
        # Check dependency validity
        task_ids = {task.id for task in plan.tasks}
        for task in plan.tasks:
            for dep_id in task.depends_on:
                if dep_id not in task_ids:
                    issues.append(f"Task '{task.name}' depends on non-existent task: {dep_id}")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "can_execute": len(issues) == 0
        }
    
    def _has_circular_dependencies(self, plan: ExecutionPlan) -> bool:
        """Check for circular dependencies using DFS"""
        def has_cycle(task_id: str, visited: set, rec_stack: set) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)
            
            task = plan.get_task(task_id)
            if task:
                for dep_id in task.depends_on:
                    if dep_id not in visited:
                        if has_cycle(dep_id, visited, rec_stack):
                            return True
                    elif dep_id in rec_stack:
                        return True
            
            rec_stack.remove(task_id)
            return False
        
        visited = set()
        for task in plan.tasks:
            if task.id not in visited:
                if has_cycle(task.id, visited, set()):
                    return True
        
        return False
    
    async def optimize_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Optimize execution plan for better performance
        
        - Reorder tasks for better parallelization
        - Combine similar tasks
        - Eliminate redundant steps
        """
        # For now, return plan as-is
        # Can be enhanced with actual optimization logic
        logger.info("Plan optimization not yet implemented, returning original plan")
        return plan
