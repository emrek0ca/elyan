"""
ComputerUseTool — Claude Computer Use Implementation for Elyan

Screenshot → VLM Analysis → Action Planning → Execution → Loop
100% local, zero cloud, zero cost.
"""

import asyncio
import time
from typing import Optional, Literal
from pydantic import BaseModel
from dataclasses import dataclass, field
from datetime import datetime

from core.observability.logger import get_structured_logger

slog = get_structured_logger("computer_use")


# ============================================================================
# DATA MODELS
# ============================================================================

class ComputerAction(BaseModel):
    """Structured representation of a single user action"""
    action_type: Literal[
        "mouse_move",
        "left_click",
        "right_click",
        "double_click",
        "type",
        "scroll",
        "drag",
        "hotkey",
        "wait",
        "noop"
    ]

    # Position parameters
    x: Optional[int] = None
    y: Optional[int] = None
    x2: Optional[int] = None  # For drag destination
    y2: Optional[int] = None

    # Text input
    text: Optional[str] = None

    # Scroll parameters
    dx: Optional[int] = None
    dy: Optional[int] = None

    # Hotkey parameters
    key_combination: Optional[list[str]] = None

    # Metadata
    confidence: float = 1.0
    reasoning: Optional[str] = None
    wait_ms: int = 300


class ComputerUseTask(BaseModel):
    """Task metadata for computer use operations"""
    task_id: str
    user_intent: str
    max_steps: int = 25
    approval_level: Literal["AUTO", "CONFIRM", "SCREEN", "TWO_FA"] = "CONFIRM"
    created_at: float
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    steps: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[float] = None


# ============================================================================
# MAIN TOOL
# ============================================================================

class ComputerUseTool:
    """
    Autonomous desktop control tool (Claude Computer Use compatible)

    Loop:
    1. Take screenshot
    2. Analyze with VLM (detect UI elements)
    3. Plan next action with LLM
    4. Execute action
    5. Check if task complete
    6. Repeat (max 25 steps)
    """

    def __init__(self, max_steps: int = 25, model: str = "qwen2.5-vl:7b"):
        """
        Initialize ComputerUseTool

        Args:
            max_steps: Maximum number of action steps
            model: VLM model name (ollama compatible)
        """
        self.max_steps = max_steps
        self.model = model

        # NOTE: Actual components will be injected when available
        # For now, this is a skeleton
        self.actuator = None      # Will import RealTimeActuator
        self.vision = None        # Will import VisionAnalyzer
        self.planner = None       # Will import ActionPlanner
        self.executor = None      # Will import ActionExecutor

        self.step_count = 0
        self.evidence = []
        self.action_trace = []

        slog.log_event("computer_use_tool_init", {
            "max_steps": max_steps,
            "model": model
        })

    async def execute_task(
        self,
        user_intent: str,
        initial_screenshot: Optional[bytes] = None,
        approval_callback: Optional[callable] = None
    ) -> dict:
        """
        Execute a computer use task

        Args:
            user_intent: Natural language instruction
            initial_screenshot: Optional initial screenshot
            approval_callback: Approval function for actions

        Returns:
            {
                "status": "completed|failed|max_steps_reached",
                "result": "extracted_data",
                "steps": 7,
                "evidence": ["ss_1", "ss_2", ...],
                "action_trace": [...]
            }
        """
        task_id = f"task_{int(time.time())}"
        task = ComputerUseTask(
            task_id=task_id,
            user_intent=user_intent,
            max_steps=self.max_steps,
            created_at=time.time()
        )

        try:
            task.status = "running"

            for self.step_count in range(self.max_steps):
                # Step 1: Take screenshot
                # TODO: Replace with actual screenshot
                screenshot = b"placeholder"
                screenshot_id = f"ss_{self.step_count}"
                self.evidence.append(screenshot_id)

                # Step 2: Analyze with VLM
                # TODO: Call self.vision.analyze(screenshot)
                screen_analysis = {
                    "elements": [],
                    "description": "placeholder analysis"
                }

                # Step 3: Plan action
                # TODO: Call self.planner.plan_next_action()
                action = ComputerAction(
                    action_type="wait",
                    reasoning="Skeleton implementation"
                )

                # Step 4: Check approval
                if approval_callback:
                    approved = await approval_callback(action, screenshot)
                    if not approved:
                        return {
                            "status": "cancelled",
                            "reason": "user_rejected_action",
                            "steps": self.step_count,
                            "evidence": self.evidence
                        }

                # Step 5: Execute action
                # TODO: Call self.executor.execute(action)
                execution_result = {"success": True}

                self.action_trace.append({
                    "step": self.step_count,
                    "action": action.model_dump(),
                    "result": execution_result,
                    "screenshot_id": screenshot_id
                })

                # Step 6: Check if task complete
                if execution_result.get("task_completed"):
                    task.status = "completed"
                    task.result = execution_result.get("extracted_data")
                    task.steps = self.action_trace
                    task.evidence = self.evidence
                    task.completed_at = time.time()

                    slog.log_event("computer_use_task_completed", {
                        "task_id": task_id,
                        "steps": self.step_count + 1,
                        "duration_ms": int((task.completed_at - task.created_at) * 1000)
                    })

                    return task.model_dump()

                # Step 7: Natural delay
                await asyncio.sleep(action.wait_ms / 1000.0)

            # Max steps reached
            task.status = "failed"
            task.error = "max_steps_reached"
            task.steps = self.action_trace
            task.evidence = self.evidence
            task.completed_at = time.time()

            return task.model_dump()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.steps = self.action_trace
            task.evidence = self.evidence
            task.completed_at = time.time()

            slog.log_event("computer_use_task_error", {
                "task_id": task_id,
                "error": str(e),
                "steps": self.step_count
            }, level="error")

            return task.model_dump()


# ============================================================================
# SINGLETON
# ============================================================================

_computer_use_tool: Optional[ComputerUseTool] = None


def get_computer_use_tool(max_steps: int = 25) -> ComputerUseTool:
    """Get or create ComputerUseTool singleton"""
    global _computer_use_tool
    if _computer_use_tool is None:
        _computer_use_tool = ComputerUseTool(max_steps=max_steps)
    return _computer_use_tool
