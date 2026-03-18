"""
Vision-Guided Automation Loop

Observe → Reason → Act → Verify cycle using screenshots + LLM analysis.

The loop:
1. OBSERVE: Take screenshot of current screen state
2. REASON: Send screenshot to LLM with task context, get next action
3. ACT: Execute the action (click, type, scroll, key press)
4. VERIFY: Take new screenshot, ask LLM if goal was achieved
5. REPEAT or DONE

Integration: Called from agentic_loop or directly from agent for UI tasks.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("vision_automation")

# ── Constants ──────────────────────────────────────────────────

MAX_VISION_STEPS = 8  # Safety: max actions per automation run
SCREENSHOT_DELAY = 0.5  # Seconds to wait after action before next screenshot
VISION_TIMEOUT = 15.0  # Max seconds for a single LLM vision call


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    KEY = "key"
    WAIT = "wait"
    DONE = "done"
    FAIL = "fail"


@dataclass
class VisionAction:
    """A single action decided by the LLM from screenshot analysis."""
    action_type: ActionType
    target: str = ""  # Human-readable description of what to interact with
    x: int = 0
    y: int = 0
    text: str = ""  # For TYPE action
    key: str = ""  # For KEY action (e.g., "enter", "tab")
    scroll_direction: str = "down"  # For SCROLL action
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class VisionStep:
    """Record of one observe→reason→act cycle."""
    step_number: int
    action: VisionAction
    screenshot_path: str = ""
    success: bool = False
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0


@dataclass
class VisionAutomationResult:
    """Result of a full vision automation run."""
    goal: str
    success: bool = False
    steps: List[VisionStep] = field(default_factory=list)
    total_steps: int = 0
    total_duration_ms: float = 0.0
    final_state: str = ""
    error: str = ""


class VisionAutomationLoop:
    """
    Screenshot-driven automation loop.

    Uses LLM vision to analyze screenshots and decide next actions,
    then executes them via pyautogui/coordinate_mapper.
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client
        self._mapper = None  # Lazy-loaded CoordinateMapper
        self._screenshot_fn = None  # Lazy-loaded screenshot function

    def _ensure_deps(self):
        """Lazy-load dependencies to avoid import errors when not needed."""
        if self._mapper is None:
            try:
                from core.vision_dom.coordinate_mapper import CoordinateMapper
                self._mapper = CoordinateMapper()
            except ImportError:
                logger.warning("CoordinateMapper not available — pyautogui missing")
                self._mapper = None

        if self._screenshot_fn is None:
            try:
                from tools.system_tools import take_screenshot
                self._screenshot_fn = take_screenshot
            except ImportError:
                logger.warning("take_screenshot not available")
                self._screenshot_fn = None

    async def run(
        self,
        goal: str,
        llm_client=None,
        max_steps: int = MAX_VISION_STEPS,
        context: str = "",
    ) -> VisionAutomationResult:
        """
        Run the vision automation loop for a goal.

        Args:
            goal: Natural language description of what to achieve
            llm_client: LLM client with vision/generate capabilities
            max_steps: Maximum number of action steps
            context: Additional context about current state
        """
        client = llm_client or self._llm
        if not client:
            return VisionAutomationResult(
                goal=goal, error="No LLM client available for vision analysis"
            )

        self._ensure_deps()
        if not self._mapper:
            return VisionAutomationResult(
                goal=goal, error="GUI dependencies (pyautogui) not available"
            )
        if not self._screenshot_fn:
            return VisionAutomationResult(
                goal=goal, error="Screenshot function not available"
            )

        result = VisionAutomationResult(goal=goal)
        start_time = time.time()
        history: List[Dict[str, str]] = []  # Action history for context

        for step_num in range(1, max_steps + 1):
            step_start = time.time()

            # ── 1. OBSERVE: Take screenshot ──
            screenshot_result = await self._take_screenshot()
            if not screenshot_result.get("success"):
                result.error = f"Screenshot failed: {screenshot_result.get('error', 'unknown')}"
                break

            screenshot_path = screenshot_result.get("path", "")

            # ── 2. REASON: Ask LLM what to do next ──
            action = await self._reason(
                goal=goal,
                screenshot_path=screenshot_path,
                history=history,
                context=context,
                llm_client=client,
                step=step_num,
                max_steps=max_steps,
            )

            step = VisionStep(
                step_number=step_num,
                action=action,
                screenshot_path=screenshot_path,
                duration_ms=(time.time() - step_start) * 1000,
            )

            # ── Check if done or failed ──
            if action.action_type == ActionType.DONE:
                step.success = True
                result.steps.append(step)
                result.success = True
                result.final_state = action.reasoning
                break

            if action.action_type == ActionType.FAIL:
                result.steps.append(step)
                result.error = action.reasoning
                break

            # ── 3. ACT: Execute the action ──
            act_success = await self._execute_action(action)
            step.success = act_success
            result.steps.append(step)

            history.append({
                "step": str(step_num),
                "action": action.action_type.value,
                "target": action.target,
                "success": str(act_success),
            })

            if not act_success:
                logger.warning(f"Step {step_num} action failed: {action.action_type}")
                # Don't break — LLM might recover on next step

            # ── 4. Brief wait for UI to settle ──
            await asyncio.sleep(SCREENSHOT_DELAY)

        result.total_steps = len(result.steps)
        result.total_duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Vision automation {'SUCCESS' if result.success else 'INCOMPLETE'}: "
            f"{result.total_steps} steps in {result.total_duration_ms:.0f}ms"
        )
        return result

    # ── Screenshot ─────────────────────────────────────────────

    async def _take_screenshot(self) -> Dict[str, Any]:
        """Take a screenshot and return path."""
        try:
            result = await self._screenshot_fn()
            return result
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return {"success": False, "error": str(e)}

    # ── LLM Reasoning ──────────────────────────────────────────

    async def _reason(
        self,
        goal: str,
        screenshot_path: str,
        history: List[Dict],
        context: str,
        llm_client,
        step: int,
        max_steps: int,
    ) -> VisionAction:
        """Ask LLM to analyze screenshot and decide next action."""

        history_text = ""
        if history:
            parts = [f"  Step {h['step']}: {h['action']} on '{h['target']}' → {'OK' if h['success'] == 'True' else 'FAILED'}" for h in history[-5:]]
            history_text = "\nPrevious actions:\n" + "\n".join(parts)

        prompt = (
            f"You are a vision-guided automation agent. Analyze the screenshot and decide the next action.\n\n"
            f"GOAL: {goal}\n"
            f"Step: {step}/{max_steps}\n"
            f"{context}\n"
            f"{history_text}\n\n"
            "Analyze what you see on the screen. Decide ONE action:\n"
            "- click: Click at coordinates (x, y) on a specific UI element\n"
            "- type: Type text (optionally at coordinates)\n"
            "- scroll: Scroll up/down\n"
            "- key: Press a key (enter, tab, escape, etc.)\n"
            "- wait: Wait for UI to load\n"
            "- done: Goal is achieved\n"
            "- fail: Goal cannot be achieved\n\n"
            "Return ONLY valid JSON (no markdown fences):\n"
            '{"action": "click|type|scroll|key|wait|done|fail", '
            '"target": "description of element", '
            '"x": 0, "y": 0, '
            '"text": "", "key": "", "scroll_direction": "down", '
            '"confidence": 0.0, '
            '"reasoning": "why this action"}'
        )

        try:
            # Try vision-capable call first (image + text)
            raw = await self._call_vision_llm(llm_client, prompt, screenshot_path)
            return self._parse_action(raw)
        except Exception as e:
            logger.error(f"Vision reasoning failed: {e}")
            return VisionAction(
                action_type=ActionType.FAIL,
                reasoning=f"LLM reasoning error: {e}",
            )

    async def _call_vision_llm(self, llm_client, prompt: str, image_path: str) -> str:
        """Call LLM with vision capabilities — tries analyze_image first, falls back to text-only."""
        # Method 1: Use vision tools directly (Gemini/Ollama multimodal)
        try:
            from tools.vision_tools import analyze_image
            result = await analyze_image(
                image_path=image_path,
                prompt=prompt,
                analysis_type="ui_analysis",
                language="tr",
            )
            if result.get("success") and result.get("analysis"):
                return result["analysis"]
        except Exception as e:
            logger.debug(f"Vision tool failed, trying text LLM: {e}")

        # Method 2: Text-only LLM (no image, reduced accuracy but still useful)
        try:
            return await llm_client.generate(
                prompt + "\n\n(Note: screenshot not available, reason from context only)",
                role="inference",
            )
        except Exception as e:
            raise RuntimeError(f"All LLM methods failed: {e}")

    def _parse_action(self, raw: str) -> VisionAction:
        """Parse LLM JSON response into VisionAction."""
        try:
            # Extract JSON from possible markdown wrapping
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
            else:
                data = json.loads(text)

            action_str = data.get("action", "fail").lower()
            try:
                action_type = ActionType(action_str)
            except ValueError:
                action_type = ActionType.FAIL

            return VisionAction(
                action_type=action_type,
                target=str(data.get("target", "")),
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                text=str(data.get("text", "")),
                key=str(data.get("key", "")),
                scroll_direction=str(data.get("scroll_direction", "down")),
                confidence=float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Action parse error: {e}, raw: {raw[:200]}")
            return VisionAction(
                action_type=ActionType.FAIL,
                reasoning=f"Could not parse LLM response: {e}",
            )

    # ── Action Execution ───────────────────────────────────────

    async def _execute_action(self, action: VisionAction) -> bool:
        """Execute a vision-decided action using CoordinateMapper."""
        try:
            if action.action_type == ActionType.CLICK:
                return self._mapper.click(action.x, action.y)

            elif action.action_type == ActionType.TYPE:
                return self._mapper.type_text(
                    action.text,
                    x=action.x if action.x > 0 else None,
                    y=action.y if action.y > 0 else None,
                )

            elif action.action_type == ActionType.SCROLL:
                try:
                    import pyautogui
                    amount = -3 if action.scroll_direction == "up" else 3
                    pyautogui.scroll(amount)
                    return True
                except Exception:
                    return False

            elif action.action_type == ActionType.KEY:
                try:
                    import pyautogui
                    pyautogui.press(action.key)
                    return True
                except Exception:
                    return False

            elif action.action_type == ActionType.WAIT:
                await asyncio.sleep(1.0)
                return True

            return False
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return False


# ── Convenience Function ───────────────────────────────────────

async def run_vision_task(
    goal: str,
    llm_client=None,
    max_steps: int = MAX_VISION_STEPS,
    context: str = "",
) -> VisionAutomationResult:
    """Run a vision-guided automation task. Entry point for external callers."""
    loop = VisionAutomationLoop(llm_client=llm_client)
    return await loop.run(goal=goal, llm_client=llm_client, max_steps=max_steps, context=context)


# ── Tool Registration Helper ──────────────────────────────────

async def vision_automate(
    goal: str,
    max_steps: int = 5,
) -> Dict[str, Any]:
    """
    Tool-compatible wrapper for vision automation.
    Registered as 'vision_automate' in tools registry.
    """
    try:
        from core.llm_client import LLMClient
        client = LLMClient()
    except Exception:
        client = None

    result = await run_vision_task(goal=goal, llm_client=client, max_steps=max_steps)
    return {
        "success": result.success,
        "goal": result.goal,
        "steps_taken": result.total_steps,
        "duration_ms": result.total_duration_ms,
        "final_state": result.final_state,
        "error": result.error,
        "actions": [
            {
                "step": s.step_number,
                "action": s.action.action_type.value,
                "target": s.action.target,
                "reasoning": s.action.reasoning,
                "success": s.success,
            }
            for s in result.steps
        ],
    }
