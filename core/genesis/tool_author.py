"""
Elyan Tool Author — Autonomous tool generation

When a required tool is missing, generates it via LLM, tests it,
and registers it in the tool registry.
"""

import ast
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("tool_author")


class ToolAuthor:
    """Autonomously writes, tests, and registers new tools."""

    def __init__(self):
        self.authored_tools_dir = Path.home() / ".elyan" / "authored_tools"
        self.authored_tools_dir.mkdir(parents=True, exist_ok=True)
        self.authored_count = 0

    async def author_tool(
        self,
        tool_name: str,
        description: str,
        llm_client=None,
    ) -> Dict[str, Any]:
        """Generate a new tool from description."""
        if not llm_client:
            return {"success": False, "error": "LLM client required for tool authoring"}

        logger.info(f"Authoring new tool: {tool_name}")

        # Generate tool code
        prompt = f"""Write a Python async function called '{tool_name}' that does the following:
{description}

Requirements:
- Function must be async
- Must return a Dict[str, Any] with at least a 'success' key
- Include proper error handling
- Include a docstring
- Import only standard library or commonly available packages
- Return ONLY the Python code, no markdown fences

Example format:
async def {tool_name}(**kwargs) -> dict:
    \"\"\"Description here.\"\"\"
    try:
        # implementation
        return {{"success": True, "result": ...}}
    except Exception as e:
        return {{"success": False, "error": str(e)}}
"""
        try:
            code = await llm_client.generate(prompt, role="inference")
            # Strip markdown if present
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else code

            # Validate syntax
            try:
                ast.parse(code)
            except SyntaxError as se:
                return {"success": False, "error": f"Generated code has syntax error: {se}"}

            # Write to file
            tool_path = self.authored_tools_dir / f"{tool_name}.py"
            tool_path.write_text(code)

            # Test execution
            test_result = await self._test_tool(tool_path, tool_name)

            if test_result.get("success"):
                self.authored_count += 1
                return {
                    "success": True,
                    "tool_name": tool_name,
                    "path": str(tool_path),
                    "test_passed": True,
                    "total_authored": self.authored_count,
                }
            else:
                return {
                    "success": False,
                    "error": f"Tool test failed: {test_result.get('error')}",
                    "path": str(tool_path),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _test_tool(self, tool_path: Path, tool_name: str) -> Dict[str, Any]:
        """Test the authored tool with a dry run."""
        try:
            from core.sandbox.selector import sandbox
            test_code = f"""
import asyncio
import sys
sys.path.insert(0, '{tool_path.parent}')
from {tool_name} import {tool_name}

async def test():
    result = await {tool_name}()
    assert isinstance(result, dict), "Tool must return a dict"
    assert "success" in result, "Result must have 'success' key"
    print("TEST PASSED")

asyncio.run(test())
"""
            result = await sandbox.execute_code(test_code, language="python")
            return {
                "success": "TEST PASSED" in result.get("stdout", ""),
                "output": result.get("stdout", ""),
                "error": result.get("stderr", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_authored(self) -> list:
        """List all authored tools."""
        return [f.stem for f in self.authored_tools_dir.glob("*.py")]


# Global instance
tool_author = ToolAuthor()
