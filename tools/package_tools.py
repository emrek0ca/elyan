"""
Elyan Package Tools — pip, npm, yarn, cargo, brew management
"""

import asyncio
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("package_tools")


async def _run_pkg(cmd: List[str], cwd: str = None, timeout: int = 120) -> Dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace")[:20000],
            "stderr": stderr.decode(errors="replace")[:5000],
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def pip_install(packages: List[str], upgrade: bool = False) -> Dict[str, Any]:
    args = ["pip", "install"] + packages
    if upgrade:
        args.append("--upgrade")
    return await _run_pkg(args)


async def pip_list() -> Dict[str, Any]:
    result = await _run_pkg(["pip", "list", "--format", "json"])
    if result["success"]:
        import json
        try:
            result["packages"] = json.loads(result["stdout"])
        except Exception:
            pass
    return result


async def npm_install(packages: List[str] = None, cwd: str = ".", dev: bool = False) -> Dict[str, Any]:
    args = ["npm", "install"]
    if packages:
        args += packages
    if dev:
        args.append("--save-dev")
    return await _run_pkg(args, cwd=cwd)


async def npm_run(script: str, cwd: str = ".") -> Dict[str, Any]:
    return await _run_pkg(["npm", "run", script], cwd=cwd)


async def brew_install(packages: List[str]) -> Dict[str, Any]:
    return await _run_pkg(["brew", "install"] + packages)


async def brew_list() -> Dict[str, Any]:
    return await _run_pkg(["brew", "list"])
