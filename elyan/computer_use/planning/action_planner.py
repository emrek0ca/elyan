"""ActionPlanner — LLM-based action planning

Uses local LLM (via litellm) to generate structured ComputerAction
based on task intent and current screen state.
"""

import json
from typing import Optional

from core.observability.logger import get_structured_logger
from elyan.computer_use.tool import ComputerAction
from elyan.computer_use.vision.analyzer import ScreenAnalysisResult

slog = get_structured_logger("action_planner")


class ActionPlanner:
    """LLM-powered action planning"""

    def __init__(self, model: str = "mistral:latest"):
        """
        Initialize ActionPlanner

        Args:
            model: LLM model (local via ollama, or cloud via litellm)
        """
        self.model = model
        self.client = None  # Lazy load

    async def _ensure_client(self):
        """Lazy load LLM client"""
        if self.client is None:
            try:
                import litellm
                self.client = litellm
            except ImportError:
                # Fallback to ollama
                try:
                    import ollama
                    self.client = ollama
                except ImportError:
                    raise RuntimeError(
                        "Neither litellm nor ollama available. "
                        "Install with: pip install litellm ollama"
                    )

    async def plan_next_action(
        self,
        user_intent: str,
        screen_analysis: ScreenAnalysisResult,
        previous_actions: list[dict]
    ) -> ComputerAction:
        """
        Plan the next action using LLM

        Args:
            user_intent: The task goal
            screen_analysis: Current screen state from VLM
            previous_actions: History of actions taken

        Returns:
            ComputerAction to execute next
        """
        await self._ensure_client()

        try:
            # Build prompt
            prompt = self._build_planning_prompt(
                user_intent,
                screen_analysis,
                previous_actions
            )

            slog.log_event("action_planning_start", {
                "intent": user_intent[:50],
                "previous_steps": len(previous_actions),
                "elements_available": len(screen_analysis.elements)
            })

            # Call LLM
            response = await self._call_llm(prompt)

            # Parse response
            action = self._parse_action_response(response)

            slog.log_event("action_planning_complete", {
                "action_type": action.action_type,
                "confidence": action.confidence
            })

            return action

        except Exception as e:
            slog.log_event("action_planning_error", {
                "error": str(e)
            }, level="error")

            # Fallback: wait and retry
            return ComputerAction(
                action_type="wait",
                wait_ms=500,
                reasoning="Planning failed, retrying..."
            )

    def _build_planning_prompt(
        self,
        intent: str,
        screen: ScreenAnalysisResult,
        history: list[dict]
    ) -> str:
        """Build LLM prompt for action planning"""
        elements_str = ""
        for i, el in enumerate(screen.elements[:10]):  # Top 10 elements
            elements_str += f"  {i}: [{el.element_type}] '{el.text or el.element_id}' @ ({el.bbox[0]}, {el.bbox[1]})\n"

        history_str = ""
        for action in history[-3:]:  # Last 3 actions
            history_str += f"  - {action.get('action', {}).get('action_type')} at step {action.get('step')}\n"

        prompt = f"""
Task: {intent}

Current Screen:
  Title: {screen.page_title}
  App: {screen.current_app}
  Description: {screen.screen_description}
  URL: {screen.current_url}

Available UI Elements:
{elements_str}

Previous Actions:
{history_str if history_str else "  (none yet)"}

Plan the NEXT action to progress towards the task.

Return ONLY valid JSON (no markdown, no extra text):
{{
    "action_type": "left_click|right_click|type|scroll|drag|hotkey|wait|noop",
    "x": <int or null>,
    "y": <int or null>,
    "text": "<string or null>",
    "key_combination": ["ctrl", "c"] or null,
    "dx": <int or null>,
    "dy": <int or null>,
    "confidence": 0.0-1.0,
    "reasoning": "why this action"
}}

Rules:
- If task is complete, set action_type to "noop" with task_completed metadata
- Use element coordinates from the list above
- Only type if there's a text_field visible
- Click is the most common action
- Wait (500ms) if you need to let page load
"""
        return prompt

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM with prompt, return response text"""
        try:
            if hasattr(self.client, 'chat'):
                # ollama interface
                response = self.client.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False
                )
                return response['message']['content']
            elif hasattr(self.client, 'completion'):
                # litellm interface
                response = await self.client.acompletion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content
            else:
                raise RuntimeError("Unknown LLM client interface")
        except Exception as e:
            slog.log_event("llm_call_error", {
                "model": self.model,
                "error": str(e)
            }, level="error")
            raise

    def _parse_action_response(self, response_text: str) -> ComputerAction:
        """
        Parse LLM response into ComputerAction

        LLM might include markdown or extra text, extract JSON
        """
        try:
            # Try direct JSON parse
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try extracting from markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    data = json.loads(response_text[start:end].strip())
                else:
                    raise ValueError("Invalid JSON in markdown block")
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                if end > start:
                    data = json.loads(response_text[start:end].strip())
                else:
                    raise ValueError("Invalid JSON in code block")
            else:
                raise ValueError(f"Could not parse LLM response: {response_text[:100]}")

        # Validate and construct ComputerAction
        try:
            action = ComputerAction(
                action_type=data.get("action_type", "wait"),
                x=data.get("x"),
                y=data.get("y"),
                x2=data.get("x2"),
                y2=data.get("y2"),
                text=data.get("text"),
                dx=data.get("dx"),
                dy=data.get("dy"),
                key_combination=data.get("key_combination"),
                confidence=float(data.get("confidence", 0.8)),
                reasoning=data.get("reasoning"),
                wait_ms=int(data.get("wait_ms", 300))
            )
            return action
        except Exception as e:
            slog.log_event("action_parsing_error", {
                "response_preview": str(data)[:100],
                "error": str(e)
            }, level="error")
            # Fallback: wait
            return ComputerAction(action_type="wait", wait_ms=500)


# ============================================================================
# SINGLETON
# ============================================================================

_planner: Optional[ActionPlanner] = None


async def get_action_planner(model: str = "mistral:latest") -> ActionPlanner:
    """Get or create ActionPlanner singleton"""
    global _planner
    if _planner is None:
        _planner = ActionPlanner(model=model)
    return _planner
