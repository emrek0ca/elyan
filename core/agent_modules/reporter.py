"""
Agent Reporter — Response formatting and delivery module.

Handles: response formatting, attachment management, evidence compilation.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)


class AgentReporter:
    """
    Formats and delivers execution results to the user.

    Responsibilities:
    - Format responses based on channel (CLI, Telegram, Web)
    - Compile execution evidence
    - Generate summary reports for complex tasks
    - Manage attachment delivery
    """

    def __init__(self, agent: "Agent"):
        self.agent = agent

    def format_response(
        self,
        result: Any,
        action: str,
        channel: str = "cli",
        verification: Optional[Dict] = None,
        loop_result: Optional[Dict] = None,
    ) -> str:
        """
        Format execution result into user-friendly response.
        """
        if isinstance(result, str):
            response = result
        elif isinstance(result, dict):
            response = str(result.get("message", "") or result.get("text", "") or result.get("result", ""))
        else:
            response = str(result or "")

        # Add verification summary if available
        if verification and not verification.get("passed", True):
            issues = verification.get("issues", [])
            if issues:
                response += "\n\n⚠️ **Doğrulama Notları:**\n"
                for issue in issues:
                    response += f"- {issue}\n"

        # Add agentic loop summary if corrections were made
        if loop_result and loop_result.get("total_iterations", 0) > 1:
            status = loop_result.get("final_status", "")
            iterations = loop_result.get("total_iterations", 0)
            improvements = loop_result.get("improvements_made", [])
            if improvements:
                response += f"\n\n🔄 **Otonom Düzeltme ({iterations} iterasyon):**\n"
                for imp in improvements:
                    response += f"- {imp}\n"

        return response.strip()

    def build_execution_report(
        self,
        plan: Dict[str, Any],
        execution_result: Dict[str, Any],
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build a comprehensive execution report.
        """
        return {
            "plan": {
                "total_steps": len(plan.get("steps", [])),
                "complexity": plan.get("estimated_complexity", 0),
            },
            "execution": {
                "completed": execution_result.get("completed_steps", 0),
                "total": execution_result.get("total_steps", 0),
                "success": execution_result.get("success", False),
            },
            "verification": {
                "passed": verification.get("passed", True),
                "checks": verification.get("checks", []),
                "issues": verification.get("issues", []),
                "score": verification.get("score", 1.0),
            },
        }
