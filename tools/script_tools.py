import asyncio
from typing import Any
from security.whitelist import is_command_allowed
from config.settings import TASK_TIMEOUT

async def run_command(command: str) -> dict[str, Any]:
    allowed, msg = is_command_allowed(command)
    if not allowed:
        return {"success": False, "error": msg}

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=None
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TASK_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"success": False, "error": f"Command timed out ({TASK_TIMEOUT}s)"}

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if len(stdout_str) > 4000:
            stdout_str = stdout_str[:4000] + "\n... (truncated)"

        if process.returncode != 0:
            return {
                "success": False,
                "error": stderr_str or f"Command failed with code {process.returncode}",
                "stdout": stdout_str,
                "return_code": process.returncode
            }

        return {
            "success": True,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "return_code": process.returncode
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
