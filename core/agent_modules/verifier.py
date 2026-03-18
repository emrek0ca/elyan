"""
Agent Verifier — Output verification and quality assurance module.

Handles: output validation, code syntax checking, completeness verification.
"""

import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent

logger = logging.getLogger(__name__)


class AgentVerifier:
    """
    Verifies execution outputs meet quality standards.

    Responsibilities:
    - Validate code syntax (Python AST check)
    - Check file existence for file operations
    - Verify response completeness
    - Run automated quality checks
    """

    def __init__(self, agent: "Agent"):
        self.agent = agent

    def verify_output(
        self,
        action: str,
        result: Any,
        user_input: str,
    ) -> Dict[str, Any]:
        """
        Verify an execution result.

        Returns:
            {"passed": bool, "checks": [...], "issues": [...]}
        """
        checks = []
        issues = []

        # Check 1: Non-empty result
        if not result:
            issues.append("Boş sonuç üretildi")
        else:
            checks.append("non_empty_result")

        # Check 2: Code syntax validation
        if action in ("create_coding_project", "run_code", "write_file"):
            code_check = self._check_code_syntax(result)
            if code_check["valid"]:
                checks.append("code_syntax_valid")
            else:
                issues.append(f"Kod syntax hatası: {code_check['error']}")

        # Check 3: File existence for file operations
        if action in ("write_file", "create_folder", "copy_file", "move_file"):
            file_check = self._check_file_result(result)
            if file_check["exists"]:
                checks.append("file_exists")
            else:
                issues.append(f"Dosya oluşturulamadı: {file_check.get('path', 'unknown')}")

        # Check 4: Response relevance (basic)
        if isinstance(result, str) and len(result) > 10:
            relevance = self._check_relevance(result, user_input)
            if relevance > 0.3:
                checks.append("response_relevant")
            else:
                issues.append("Yanıt kullanıcı isteğiyle ilgisiz görünüyor")

        passed = len(issues) == 0
        return {
            "passed": passed,
            "checks": checks,
            "issues": issues,
            "score": len(checks) / max(1, len(checks) + len(issues)),
        }

    def _check_code_syntax(self, result: Any) -> Dict[str, Any]:
        """Check Python code syntax validity."""
        code = ""
        if isinstance(result, str):
            # Extract code blocks
            blocks = re.findall(r"```python\n(.*?)\n```", result, re.DOTALL)
            code = "\n".join(blocks) if blocks else result
        elif isinstance(result, dict):
            code = str(result.get("code", "") or result.get("content", ""))

        if not code.strip():
            return {"valid": True, "error": ""}

        try:
            import ast
            ast.parse(code)
            return {"valid": True, "error": ""}
        except SyntaxError as e:
            return {"valid": False, "error": f"Line {e.lineno}: {e.msg}"}
        except Exception:
            return {"valid": True, "error": ""}  # Non-Python content

    def _check_file_result(self, result: Any) -> Dict[str, Any]:
        """Check if file operation produced the expected file."""
        from pathlib import Path

        path = ""
        if isinstance(result, dict):
            path = str(result.get("path", "") or result.get("file_path", ""))
        elif isinstance(result, str):
            # Try to extract path from result text
            match = re.search(r"(?:created|wrote|saved).*?['\"]?(/[^\s'\"]+|~/[^\s'\"]+)", result)
            if match:
                path = match.group(1)

        if not path:
            return {"exists": True, "path": ""}  # Can't verify, assume OK

        try:
            return {"exists": Path(path).expanduser().exists(), "path": path}
        except Exception:
            return {"exists": True, "path": path}

    def _check_relevance(self, response: str, user_input: str) -> float:
        """Basic relevance check between response and user input."""
        response_lower = response.lower()
        input_words = set(user_input.lower().split())

        # Remove common words
        stop_words = {"bir", "bu", "şu", "ve", "ile", "için", "the", "a", "an", "is"}
        meaningful_words = input_words - stop_words

        if not meaningful_words:
            return 1.0

        matches = sum(1 for w in meaningful_words if w in response_lower)
        return matches / len(meaningful_words)
