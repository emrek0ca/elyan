"""
core/deterministic_runner.py
─────────────────────────────────────────────────────────────────────────────
Deterministic State Machine Executor.
Executes an ExecutionPlan consisting of idempotent steps with pre/post-conditions.
Replaces open-ended LLM tool runners.
"""
from __future__ import annotations
import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("deterministic_runner")

@dataclass
class StepCondition:
    type: str  # "file_exists", "dir_exists", "min_size", "contains_text", "not_exists"
    path: str
    value: Any = None
    
    @classmethod
    def from_dict(cls, data: dict) -> StepCondition:
        return cls(
            type=data.get("type", ""),
            path=data.get("path", ""),
            value=data.get("value")
        )

@dataclass
class ExecutionStep:
    id: str
    action: str
    params: Dict[str, Any]
    preconditions: List[StepCondition] = field(default_factory=list)
    postconditions: List[StepCondition] = field(default_factory=list)
    idempotent: bool = True
    
    @classmethod
    def from_dict(cls, data: dict) -> ExecutionStep:
        return cls(
            id=data.get("id", "unknown_step"),
            action=data.get("action", ""),
            params=data.get("params", {}),
            preconditions=[StepCondition.from_dict(c) for c in data.get("preconditions", [])],
            postconditions=[StepCondition.from_dict(c) for c in data.get("postconditions", [])],
            idempotent=data.get("idempotent", True)
        )
        
@dataclass
class ExecutionPlan:
    job_id: str
    steps: List[ExecutionStep] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict) -> ExecutionPlan:
        return cls(
            job_id=data.get("job_id", ""),
            steps=[ExecutionStep.from_dict(s) for s in data.get("steps", [])]
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> ExecutionPlan:
        return cls.from_dict(json.loads(json_str))

class DeterministicToolRunner:
    """
    A robust state machine for tool execution.
    It does not generate text; it strictly follows a JSON ExecutionPlan.
    Each step must pass preconditions, execute the exact tool, and satisfy postconditions.
    """
    def __init__(self, agent_instance):
        self.agent = agent_instance
        
    async def execute_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        results = {}
        for step in plan.steps:
            logger.info(f"[DeterministicRunner] Executing Step: {step.id} - {step.action}")
            
            # 1. Evaluate Preconditions
            pre_ok, pre_reason = await self._evaluate_conditions(step.preconditions)
            if not pre_ok:
                logger.error(f"[DeterministicRunner] Precondition failed at {step.id}: {pre_reason}")
                return {"success": False, "failed_step": step.id, "stage": "precondition", "reason": pre_reason, "results": results}
                
            # 2. Execute Action
            try:
                # If creating a file, ensure parent dir exists as a built-in idempotency helper
                if step.action == "write_file" and "path" in step.params:
                    parent_dir = os.path.dirname(os.path.expanduser(step.params["path"]))
                    if parent_dir and not os.path.exists(parent_dir):
                        os.makedirs(parent_dir, exist_ok=True)

                res = await self.agent._execute_tool(step.action, step.params, step_name=step.id)
            except Exception as e:
                res = {"success": False, "error": str(e)}

            results[step.id] = res
            
            if not res.get("success"):
                logger.error(f"[DeterministicRunner] Action failed at {step.id}: {res.get('error')}")
                return {"success": False, "failed_step": step.id, "stage": "execution", "reason": res.get("error"), "results": results}
                
            # 3. Evaluate Postconditions
            post_ok, post_reason = await self._evaluate_conditions(step.postconditions)
            if not post_ok:
                logger.error(f"[DeterministicRunner] Postcondition failed at {step.id}: {post_reason}")
                return {"success": False, "failed_step": step.id, "stage": "postcondition", "reason": post_reason, "results": results}
                
        logger.info(f"[DeterministicRunner] Plan {plan.job_id} executed successfully.")
        return {"success": True, "results": results}

    async def _evaluate_conditions(self, conditions: List[StepCondition]) -> tuple[bool, str]:
        for c in conditions:
            target_path = os.path.expanduser(c.path) if c.path else ""
            
            if c.type == "file_exists":
                if not os.path.isfile(target_path): 
                    return False, f"File does not exist: {target_path}"
            elif c.type == "dir_exists":
                if not os.path.isdir(target_path): 
                    return False, f"Directory does not exist: {target_path}"
            elif c.type == "not_exists":
                if os.path.exists(target_path): 
                    return False, f"Path exists but should not: {target_path}"
            elif c.type == "min_size":
                if not os.path.isfile(target_path):
                    return False, f"File missing for size check: {target_path}"
                actual = os.path.getsize(target_path)
                expected = int(c.value or 0)
                if actual < expected:
                    return False, f"File {target_path} too small: {actual} < {expected} bytes"
            elif c.type == "contains_text":
                if not os.path.isfile(target_path):
                    return False, f"File missing for text check: {target_path}"
                try:
                    with open(target_path, "r", encoding="utf-8") as f:
                        if str(c.value) not in f.read():
                            return False, f"File {target_path} missing required text: {c.value}"
                except Exception as e:
                    return False, f"Failed to read {target_path} for text check: {e}"
        return True, ""
