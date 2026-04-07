"""
core/security/zero_trust_runtime.py
─────────────────────────────────────────────────────────────────────────────
Zero Trust Runtime (Phase 26).
Ensures any code output written by Elyan (or injected via prompt hacking)
cannot compromise the host machine. Implements AST whitelisting and
resource-bound subprocess jailing for dynamic Python executions.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from typing import Any

from core.sandbox.selector import sandbox
from utils.logger import get_logger

logger = get_logger("zero_trust")

class ZeroTrustRuntime:
    def __init__(self, use_docker: bool = False):
        self.use_docker = use_docker
        self.max_execution_sec = 10.0
        self.allowed_imports = {
            "math", "statistics", "random", "json", "re", "itertools", "collections",
            "datetime", "decimal", "fractions", "string",
        }
        self.blocked_builtins = {"eval", "exec", "globals", "locals", "__import__", "open", "input", "compile"}
        self.resource_quota = {
            "timeout_seconds": self.max_execution_sec,
            "network": False,
            "filesystem": "sandbox_only",
            "memory": "512m",
            "cpus": "1.0",
        }

    def _is_ast_safe(self, code_str: str) -> tuple[bool, str]:
        """Statically analyzes the Code snippet before running it to block RCE attempts."""
        try:
            tree = ast.parse(code_str)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split('.')[0]
                        if root not in self.allowed_imports:
                            return False, f"DISALLOWED_IMPORT: {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    root = node.module.split('.')[0] if node.module else ""
                    if root and root not in self.allowed_imports:
                        return False, f"DISALLOWED_IMPORT_FROM: {node.module}"
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in self.blocked_builtins:
                            return False, f"BANNED_BUILTIN: {node.func.id}()"
                elif isinstance(node, (ast.With, ast.AsyncWith, ast.Try)):
                    continue
            
            return True, "SAFE"
        except SyntaxError as e:
            return False, f"SYNTAX_ERROR: {e}"

    @staticmethod
    def _run_async_sync(coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _worker() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:
                error["value"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if "value" in error:
            raise error["value"]
        return result.get("value")

    def safe_evaluate_python(self, code_str: str) -> dict:
        """Runs the python code inside a heavily restricted Subprocess / Docker jail."""
        is_safe, reason = self._is_ast_safe(code_str)
        if not is_safe:
            logger.error(f"🚨 ZeroTrust Sandbox Blocked Code Execution! Reason: {reason}")
            return {
                "success": False,
                "error": f"Security Violation: {reason}",
                "quota": dict(self.resource_quota),
                "sandboxed": True,
            }

        logger.debug("🛡️ ZeroTrust AST Check Passed. Executing payload in sandbox selector...")
        try:
            result = self._run_async_sync(
                sandbox.execute_code(
                    code_str,
                    language="python",
                    prefer_docker=bool(self.use_docker),
                    timeout=int(self.max_execution_sec),
                )
            )
            if isinstance(result, dict):
                result.setdefault("quota", dict(self.resource_quota))
                result.setdefault("sandboxed", True)
                return result
            return {"success": False, "error": "sandbox_result_invalid", "quota": dict(self.resource_quota), "sandboxed": True}
        except Exception as e:
            logger.warning(f"ZeroTrust sandbox execution failed: {e}")
            return {"success": False, "error": str(e), "quota": dict(self.resource_quota), "sandboxed": True}

# Export Singleton
zero_trust_env = ZeroTrustRuntime(use_docker=False)
