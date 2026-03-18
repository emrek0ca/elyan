"""
Agent Planner — Task planning and decomposition module.

Extracted from agent.py to provide clean task planning logic.
Handles: goal graph building, task spec creation, multi-step plan generation.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)


class AgentPlanner:
    """
    Plans and decomposes user requests into executable task specifications.

    Responsibilities:
    - Parse user intent into structured task spec
    - Build goal graphs for complex requests
    - Create multi-step execution plans with dependencies
    - Estimate complexity and resource requirements
    """

    def __init__(self, agent: "Agent"):
        self.agent = agent

    async def create_plan(
        self,
        user_input: str,
        intent: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an execution plan from user input and parsed intent.

        Returns:
            Plan dict with steps, dependencies, estimated duration.
        """
        action = str(intent.get("action", "") or "")
        complexity = float(intent.get("complexity", 0.3) or 0.3)

        plan = {
            "action": action,
            "steps": [],
            "dependencies": [],
            "estimated_complexity": complexity,
            "requires_verification": complexity >= 0.5,
            "requires_agentic_loop": complexity >= 0.6,
        }

        # Simple action — single step
        if complexity < 0.4:
            plan["steps"] = [{
                "id": "step_1",
                "action": action,
                "params": intent.get("params", {}),
                "description": f"Execute {action}",
            }]
            return plan

        # Complex action — try LLM-based decomposition
        try:
            if self.agent.llm:
                decomposed = await self._llm_decompose(user_input, action, context)
                if decomposed:
                    plan["steps"] = decomposed["steps"]
                    plan["dependencies"] = decomposed.get("dependencies", [])
                    return plan
        except Exception as e:
            logger.debug(f"LLM decomposition failed: {e}")

        # Fallback: single step
        plan["steps"] = [{
            "id": "step_1",
            "action": action,
            "params": intent.get("params", {}),
            "description": user_input[:200],
        }]
        return plan

    async def _llm_decompose(
        self,
        user_input: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Use LLM to decompose a complex task into steps.

        Returns None if LLM is unavailable or fails.
        """
        if not self.agent.llm:
            return None

        prompt = (
            f"Decompose this task into 2-5 sequential steps:\n"
            f"Task: {user_input}\n"
            f"Action type: {action}\n\n"
            f"Return JSON: {{\"steps\": [{{\"id\": \"step_N\", \"action\": \"...\", "
            f"\"description\": \"...\", \"depends_on\": []}}]}}"
        )

        try:
            import json
            response = await self.agent.llm.generate(
                prompt,
                system_prompt="You are a task planner. Return valid JSON only.",
                role="planner",
            )
            if response and response.strip().startswith("{"):
                return json.loads(response)
        except Exception as e:
            logger.debug(f"LLM decomposition parse failed: {e}")

        return None

    def estimate_complexity(self, user_input: str, intent: Dict[str, Any]) -> float:
        """
        Estimate task complexity from 0.0 (trivial) to 1.0 (very complex).

        Factors:
        - Number of entities in input
        - Action type
        - Presence of multi-step keywords
        """
        score = float(intent.get("complexity", 0.3) or 0.3)

        text_lower = user_input.lower()

        # Multi-step indicators
        multi_step_words = ["ve", "sonra", "ardından", "önce", "ayrıca", "hem", "hem de"]
        for word in multi_step_words:
            if word in text_lower:
                score += 0.1

        # Complex action types
        complex_actions = {"create_coding_project", "advanced_research",
                          "generate_document_pack", "research_document_delivery"}
        action = str(intent.get("action", ""))
        if action in complex_actions:
            score += 0.2

        return min(1.0, max(0.0, score))
