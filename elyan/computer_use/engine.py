from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from core.observability.logger import get_structured_logger
from core.realtime_actuator import get_realtime_actuator
from config.settings_manager import SettingsPanel

slog = get_structured_logger("computer_use_engine")


class ComputerAction(BaseModel):
    action_type: Literal["mouse_move", "left_click", "right_click", "double_click", "type", "scroll", "drag", "hotkey", "wait", "noop"]
    x: Optional[int] = None
    y: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    text: Optional[str] = None
    dx: Optional[int] = None
    dy: Optional[int] = None
    key_combination: Optional[list[str]] = None
    confidence: float = 1.0
    reasoning: Optional[str] = None
    wait_ms: int = 300


@dataclass
class ComputerUseTask:
    task_id: str
    user_intent: str
    max_steps: int = 25
    approval_level: Literal["AUTO", "CONFIRM", "SCREEN", "TWO_FA"] = "CONFIRM"
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    steps: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    approval_requests: list[dict] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    completed_at: float | None = None
    terminal_reason: str | None = None
    retry_count: int = 0
    fallback_used: bool = False
    repair_events: list[dict] = field(default_factory=list)
    confidence_score: float = 0.0
    verification_score: float = 0.0
    fallback_path: str = ""
    repair_strategy: str = ""
    blocked_reason: str = ""

    def model_dump(self) -> dict:
        return {
            "task_id": self.task_id,
            "user_intent": self.user_intent,
            "max_steps": self.max_steps,
            "approval_level": self.approval_level,
            "created_at": self.created_at,
            "status": self.status,
            "steps": list(self.steps),
            "action_trace": list(self.steps),
            "evidence": list(self.evidence),
            "approval_requests": list(self.approval_requests),
            "result": self.result,
            "error": self.error,
            "completed_at": self.completed_at,
            "terminal_reason": self.terminal_reason,
            "retry_count": self.retry_count,
            "fallback_used": self.fallback_used,
            "repair_events": list(self.repair_events),
            "confidence_score": self.confidence_score,
            "verification_score": self.verification_score,
            "fallback_path": self.fallback_path,
            "repair_strategy": self.repair_strategy,
            "blocked_reason": self.blocked_reason,
        }


class ComputerUseEngine:
    def __init__(self, max_steps: int = 25, model: str = "qwen2.5-vl:7b") -> None:
        self.max_steps = max_steps
        self.model = model
        self.actuator = None
        self.vision = None
        self.planner = None
        self.executor = None
        self.timeout_budget_s = 20.0
        self.max_retries = 1
        self._last_health: dict[str, object] = {"status": "starting", "last_successful_run": 0.0, "fallback_active": False}

    async def _ensure_components(self) -> None:
        if self.vision is None:
            from elyan.computer_use.vision.analyzer import get_vision_analyzer
            settings = SettingsPanel()
            self.vision = await get_vision_analyzer(
                model=self.model,
                ocr_backend=str(settings.get("vision_ocr_backend", "auto") or "auto"),
                glm_ocr_model=str(settings.get("vision_ocr_model", "glm-4.1v-9b-thinking") or "glm-4.1v-9b-thinking"),
            )
        if self.planner is None:
            from elyan.computer_use.planning.action_planner import get_action_planner

            self.planner = await get_action_planner()
        if self.executor is None:
            from elyan.computer_use.executor.action_executor import get_action_executor

            self.executor = get_action_executor()
        if self.actuator is None:
            try:
                self.actuator = get_realtime_actuator()
            except Exception:
                self.actuator = None

    async def execute_task(
        self,
        user_intent: str,
        initial_screenshot: Optional[bytes] = None,
        approval_callback: Optional[callable] = None,
        session_id: Optional[str] = None,
        approval_level: str = "CONFIRM",
    ) -> dict:
        await self._ensure_components()
        from elyan.computer_use.approval import ApprovalGateFactory
        from elyan.computer_use.evidence.recorder import get_evidence_recorder

        task = ComputerUseTask(task_id=f"task_{int(time.time())}", user_intent=user_intent, max_steps=self.max_steps, approval_level=approval_level)
        task.status = "running"
        previous_screen_signature = ""
        previous_action_signature = ""
        approval_gate = ApprovalGateFactory.create_gate(
            session_id=str(session_id or f"session_{task.task_id}"),
            run_id=task.task_id,
            approval_level=approval_level,
        )
        recorder = await get_evidence_recorder()
        for step_index in range(self.max_steps):
            screenshot = initial_screenshot if step_index == 0 and initial_screenshot else await self._get_screenshot()
            if not screenshot:
                task.status = "blocked"
                task.error = "screenshot_unavailable"
                task.terminal_reason = "blocked:screenshot_unavailable"
                task.blocked_reason = "screenshot_unavailable"
                task.fallback_path = "re_screenshot"
                self._last_health.update({"status": "degraded", "fallback_active": True})
                break
            screenshot_id = f"ss_{step_index}_{int(time.time() * 1000)}"
            task.evidence.append(screenshot_id)
            screen_signature = hashlib.sha256(screenshot).hexdigest()[:16]
            screen_analysis = await self.vision.analyze(screenshot=screenshot, task_context=user_intent)
            task.confidence_score = self._screen_confidence(screen_analysis)
            action = await self.planner.plan_next_action(
                user_intent=user_intent,
                screen_analysis=screen_analysis,
                previous_actions=task.steps,
            )
            action_signature = hashlib.sha256(str(action.model_dump()).encode("utf-8")).hexdigest()[:16]
            if previous_screen_signature and previous_screen_signature == screen_signature and previous_action_signature == action_signature:
                if task.retry_count >= self.max_retries:
                    task.status = "failed"
                    task.error = "no_visual_change"
                    task.terminal_reason = "failed:no_visual_change"
                    task.repair_strategy = "same_step_retry"
                    task.fallback_path = "same_step_retry"
                    break
                task.retry_count += 1
                task.fallback_used = True
                task.repair_strategy = "same_step_retry"
                task.fallback_path = "same_step_retry"
                task.repair_events.append({"step": step_index, "reason": "no_visual_change", "action": "retry_with_wait"})
                await asyncio.sleep(0.5)
            approval = await approval_gate.evaluate_action(action=action, task_context=user_intent, screenshot_bytes=screenshot)
            if approval.request_id:
                task.approval_requests.append(
                    {
                        "request_id": approval.request_id,
                        "step": step_index,
                        "action_type": action.action_type,
                        "timestamp": approval.timestamp,
                        "approved": approval.approved,
                    }
                )
            if not approval.approved and approval_callback is not None:
                approval.approved = bool(await approval_callback(action, screenshot))
            if not approval.approved:
                task.status = "waiting" if approval.reason == "approval_required" else "cancelled"
                task.error = f"Action denied: {approval.reason}"
                task.terminal_reason = f"{task.status}:{approval.reason}"
                if task.status == "waiting":
                    task.blocked_reason = "approval_required"
                break
            try:
                result = await asyncio.wait_for(self.executor.execute(action), timeout=self.timeout_budget_s)
            except asyncio.TimeoutError:
                if task.retry_count >= self.max_retries:
                    task.status = "failed"
                    task.error = "executor_timeout"
                    task.terminal_reason = "failed:executor_timeout"
                    task.fallback_path = "browser_dom_hint"
                    task.repair_strategy = "re_screenshot"
                    break
                task.retry_count += 1
                task.fallback_used = True
                task.fallback_path = "browser_dom_hint"
                task.repair_strategy = "re_screenshot"
                task.repair_events.append({"step": step_index, "reason": "executor_timeout", "action": "retry_execute"})
                continue
            task.steps.append(
                {
                    "step": step_index,
                    "action": action.model_dump(),
                    "result": result,
                    "screenshot_id": screenshot_id,
                    "timestamp": time.time(),
                }
            )
            await recorder.save_screenshot(task_id=task.task_id, screenshot_id=screenshot_id, screenshot_bytes=screenshot)
            previous_screen_signature = screen_signature
            previous_action_signature = action_signature
            task.verification_score = self._verification_score(screen_analysis=screen_analysis, result=result)
            if result.get("task_completed"):
                task.status = "completed"
                task.result = str(result.get("extracted_data") or "")
                task.terminal_reason = "completed:task_completed"
                self._last_health.update({"status": "healthy", "last_successful_run": time.time(), "fallback_active": bool(task.fallback_used)})
                break
            await asyncio.sleep(max(0, int(action.wait_ms or 0)) / 1000.0)
        if task.status == "running":
            task.status = "max_steps_reached"
            task.error = "exceeded_maximum_steps"
            task.terminal_reason = "failed:max_steps_reached"
        if task.status in {"failed", "blocked", "max_steps_reached"}:
            self._last_health.update({"status": "degraded", "fallback_active": bool(task.fallback_used)})
        task.completed_at = time.time()
        await recorder.record_task(task.model_dump())
        return task.model_dump()

    async def _get_screenshot(self) -> bytes:
        if self.actuator is not None:
            try:
                payload = await self.actuator.services.take_screenshot(filename=f"computer_use_{int(time.time() * 1000)}.png")
                path = str((payload or {}).get("path") or "").strip()
                if path:
                    return Path(path).read_bytes()
            except Exception as exc:
                slog.log_event("computer_use_engine_screenshot_fallback", {"error": str(exc)}, level="warning")
                self._last_health["fallback_active"] = True
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as exc:
            slog.log_event("computer_use_engine_screenshot_error", {"error": str(exc)}, level="warning")
            return b""

    async def get_health_status(self) -> dict[str, object]:
        await self._ensure_components()
        vision_ready = bool(self.vision is not None)
        planner_ready = bool(self.planner is not None)
        executor_ready = bool(self.executor is not None)
        actuator_ready = bool(self.actuator is not None)
        ready = vision_ready and planner_ready and executor_ready
        status = str(self._last_health.get("status") or ("healthy" if ready else "degraded"))
        return {
            "status": status if ready else "degraded",
            "ready": ready,
            "components": {
                "vision": vision_ready,
                "planner": planner_ready,
                "executor": executor_ready,
                "actuator": actuator_ready,
            },
            "timeout_budget_s": self.timeout_budget_s,
            "max_retries": self.max_retries,
            "fallback_active": bool(self._last_health.get("fallback_active")),
            "last_successful_run": float(self._last_health.get("last_successful_run") or 0.0),
        }

    @staticmethod
    def _screen_confidence(screen_analysis: object) -> float:
        elements = list(getattr(screen_analysis, "elements", []) or [])
        lines = list(getattr(screen_analysis, "ocr_lines", []) or [])
        element_conf = sum(float(getattr(item, "confidence", 0.0) or 0.0) for item in elements) / max(1, len(elements))
        ocr_conf = sum(float(getattr(item, "confidence", 0.0) or 0.0) for item in lines) / max(1, len(lines))
        return round(min(1.0, element_conf * 0.6 + ocr_conf * 0.4), 4)

    @staticmethod
    def _verification_score(*, screen_analysis: object, result: dict) -> float:
        base = 0.45 if result.get("success") else 0.15
        if result.get("task_completed"):
            base += 0.35
        if getattr(screen_analysis, "ocr_text", None):
            base += 0.1
        if list(getattr(screen_analysis, "elements", []) or []):
            base += 0.1
        return round(min(1.0, base), 4)


_engine: ComputerUseEngine | None = None


def get_computer_use_engine(max_steps: int = 25) -> ComputerUseEngine:
    global _engine
    if _engine is None:
        _engine = ComputerUseEngine(max_steps=max_steps)
    return _engine


__all__ = ["ComputerAction", "ComputerUseEngine", "ComputerUseTask", "get_computer_use_engine"]
