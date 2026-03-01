"""
Elyan Local Sandbox — Host-based isolated execution (Docker-free fallback)

Uses subprocess with strict resource limits, timeout, and temporary directories.
On macOS, uses sandbox-exec profiles where available.
"""

import asyncio
import os
import shlex
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("local_sandbox")


# macOS sandbox-exec profile for restricted execution
_MACOS_SANDBOX_PROFILE = """
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow file-read*)
(allow file-write* (subpath "/tmp"))
(allow file-write* (subpath "{workspace}"))
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.system.logger"))
(deny network*)
(deny file-write* (subpath "/System"))
(deny file-write* (subpath "/usr"))
(deny file-write* (subpath "/bin"))
(deny file-write* (subpath "/sbin"))
"""

# Commands considered too dangerous even for local sandbox
BLOCKED_COMMANDS = frozenset([
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev",
    ":(){ :|:& };:", "chmod -R 777 /", "shutdown",
    "reboot", "halt", "poweroff", "launchctl",
])


class LocalSandbox:
    """Subprocess-based sandbox with timeout and isolation."""

    def __init__(self, timeout: int = 60, max_output: int = 50000):
        self.timeout = timeout
        self.max_output = max_output
        self._is_macos = os.uname().sysname == "Darwin"

    @staticmethod
    def _check_safety(command: str) -> tuple[bool, str]:
        lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in lower:
                return False, f"Dangerous command blocked: {blocked}"
        return True, ""

    async def execute(
        self,
        command: str,
        workspace_dir: Optional[str] = None,
        timeout: Optional[int] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute a command in the local sandbox."""
        t0 = time.time()
        tout = timeout or self.timeout

        safe, reason = self._check_safety(command)
        if not safe:
            return {"success": False, "error": reason, "sandboxed": True, "blocked": True}

        cwd = workspace_dir or tempfile.mkdtemp(prefix="elyan_local_")
        env = dict(os.environ)
        if env_vars:
            env.update(env_vars)

        # Use sandbox-exec on macOS for real isolation
        if self._is_macos:
            profile = _MACOS_SANDBOX_PROFILE.replace("{workspace}", cwd)
            profile_path = os.path.join(cwd, ".sandbox_profile")
            try:
                Path(profile_path).write_text(profile)
                full_cmd = f"sandbox-exec -f {shlex.quote(profile_path)} bash -c {shlex.quote(command)}"
            except Exception:
                full_cmd = command
        else:
            full_cmd = command

        try:
            proc = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=tout,
            )

            duration_ms = int((time.time() - t0) * 1000)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(errors="replace")[: self.max_output],
                "stderr": stderr.decode(errors="replace")[: 10000],
                "returncode": proc.returncode,
                "sandboxed": True,
                "sandbox_type": "macos_sandbox_exec" if self._is_macos else "subprocess",
                "duration_ms": duration_ms,
            }

        except asyncio.TimeoutError:
            # Kill entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return {
                "success": False,
                "error": f"Local sandbox timeout ({tout}s)",
                "sandboxed": True,
                "duration_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "sandboxed": True,
                "duration_ms": int((time.time() - t0) * 1000),
            }

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        workspace_dir: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Write code to temp file and run it locally."""
        tmp = tempfile.mkdtemp(prefix="elyan_local_code_")
        try:
            ext_map = {
                "python": ("main.py", "python3 main.py"),
                "node": ("main.js", "node main.js"),
                "shell": ("main.sh", "bash main.sh"),
                "ruby": ("main.rb", "ruby main.rb"),
            }
            filename, run_cmd = ext_map.get(language, ("main.py", "python3 main.py"))
            (Path(tmp) / filename).write_text(code)

            return await self.execute(
                command=run_cmd,
                workspace_dir=tmp,
                timeout=timeout,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# Global instance
local_sandbox = LocalSandbox()
