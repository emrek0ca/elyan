"""
core/tool_governance.py
─────────────────────────────────────────────────────────────────────────────
Tool Registry with JSON Schema Validation and Security Guards.
Ensures tools are used correctly and safely.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Callable, Optional
from utils.logger import get_logger

logger = get_logger("tool_governance")

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.whitelist_dirs = [str(Path.home() / "Desktop"), "/tmp"]

    def register(self, name: str, description: str, schema: Dict[str, Any], func: Callable):
        self.tools[name] = {
            "description": description,
            "schema": schema,
            "func": func
        }

    def validate_params(self, name: str, params: Dict[str, Any]):
        """Pre-flight check: Schema and Path Security."""
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")
        
        # Path Traversal Guard
        if "path" in params:
            path = str(params["path"])
            if ".." in path:
                raise PermissionError(f"Security Alert: Path traversal attempt blocked: {path}")
            
            # Whitelist check (Optional but recommended)
            # if not any(path.startswith(d) for d in self.whitelist_dirs):
            #    raise PermissionError(f"Security Alert: Access to directory not allowed: {path}")

        # Schema Validation (Basic)
        # In a real scenario, use 'jsonschema' library here.
        required = self.tools[name]["schema"].get("required", [])
        for req in required:
            if req not in params:
                raise ValueError(f"Missing required parameter '{req}' for tool '{name}'")

    async def execute(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute with pre and post flight checks."""
        try:
            self.validate_params(name, params)
            
            # Post-flight info collection (before execution)
            target_path = params.get("path")
            
            result = await self.tools[name]["func"](**params)
            
            # Post-flight verification
            if target_path and os.path.exists(target_path):
                size = os.path.getsize(target_path)
                if size == 0:
                    logger.warning(f"Post-flight warning: File {target_path} is empty (0 bytes)")
                    result["verification"] = "FAILED: Empty file"
                else:
                    result["verification"] = f"PASSED: {size} bytes written"
            
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {str(e)}")
            return {"success": False, "error": str(e), "retry_hint": "Check parameters or file permissions."}

tool_registry = ToolRegistry()
