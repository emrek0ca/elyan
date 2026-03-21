import asyncio
import sys
from typing import Any
from security.whitelist import is_command_allowed
from config.settings import TASK_TIMEOUT

async def run_command(command: str) -> dict[str, Any]:
    allowed, msg = is_command_allowed(command)
    if not allowed:
        return {"success": False, "error": msg}

    try:
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())
        from elyan.core.security import get_security_layer

        result = await get_security_layer().execute_safe(
            "run_command",
            {
                "type": "run_command",
                "action": "run_command",
                "description": command,
                "command": command,
                "language": "shell",
                "image": "alpine:3.19",
                "needs_network": False,
                "timeout": TASK_TIMEOUT,
            },
            command,
            {"source": "script_tools", "interactive": interactive},
        )
        return {
            "success": bool(result.get("success", False)),
            "status": str(result.get("status") or ("success" if result.get("success") else "failed")),
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or result.get("error") or ""),
            "return_code": int(result.get("return_code") or result.get("exit_code") or 0),
            "sandboxed": bool(result.get("sandboxed", True)),
            "backend": str(result.get("backend") or ""),
        }

    except PermissionError as e:
        return {
            "success": False,
            "status": "blocked",
            "error": str(e),
            "error_code": "APPROVAL_DENIED",
            "errors": ["APPROVAL_DENIED"],
            "sandboxed": False,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
