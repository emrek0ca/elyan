import asyncio
import subprocess
import os
import pathlib
from typing import Any, Dict, List, Optional
from core.protocol.shared_types import RiskLevel
from core.observability.logger import get_structured_logger

slog = get_structured_logger("capability_terminal")

class TerminalCapability:
    """
    Implements controlled terminal execution according to ADR-008.
    """
    def __init__(self, allowed_cwd: List[str] = None):
        self.allowed_cwd = allowed_cwd or [str(pathlib.Path.home())]

    def _is_safe_cwd(self, cwd: str) -> bool:
        resolved = pathlib.Path(cwd).expanduser().resolve()
        for root in self.allowed_cwd:
            if str(resolved).startswith(str(pathlib.Path(root).expanduser().resolve())):
                return True
        return False

    async def execute(self, command: str, cwd: str = None, timeout: int = 30) -> Dict[str, Any]:
        """Executes a command in a subprocess with timeout and capture."""
        target_cwd = cwd or str(pathlib.Path.cwd())
        
        if not self._is_safe_cwd(target_cwd):
            raise PermissionError(f"CWD not allowed: {target_cwd}")

        slog.log_event("command_execution_started", {"command": command, "cwd": target_cwd})

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=target_cwd,
                env=self._get_safe_env()
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                exit_code = process.returncode
                
                result = {
                    "exit_code": exit_code,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace")
                }
                
                slog.log_event("command_execution_finished", {
                    "command": command,
                    "exit_code": exit_code,
                    "has_stderr": bool(stderr)
                })
                
                return result

            except asyncio.TimeoutError:
                process.kill()
                slog.log_event("command_execution_timeout", {"command": command}, level="warning")
                return {"error": "timeout", "exit_code": -1}

        except Exception as e:
            logger.error(f"Terminal execution error: {e}")
            slog.log_event("command_execution_error", {"command": command, "error": str(e)}, level="error")
            return {"error": str(e), "exit_code": 1}

    def _get_safe_env(self) -> Dict[str, str]:
        """Returns a sanitized environment for subprocesses."""
        # Filter out sensitive environment variables
        safe_keys = {"PATH", "TERM", "LANG", "LC_ALL", "USER", "HOME", "SHELL"}
        env = {k: v for k, v in os.environ.items() if k in safe_keys or k.startswith("ELYAN_")}
        return env

# Global instance
terminal_capability = TerminalCapability()
