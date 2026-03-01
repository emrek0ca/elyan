"""
Elyan Git Tools — Full Git and GitHub/GitLab integration

Clone, commit, push, pull, branch, merge, diff, log, PR creation.
"""

import asyncio
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("git_tools")


async def _run_git(args: List[str], cwd: str = None) -> Dict[str, Any]:
    """Run a git command asynchronously."""
    cmd = ["git"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip(),
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Git command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def git_clone(url: str, dest: str = None) -> Dict[str, Any]:
    """Clone a git repository."""
    dest = dest or os.path.basename(url).replace(".git", "")
    result = await _run_git(["clone", url, dest])
    if result["success"]:
        result["path"] = os.path.abspath(dest)
    return result


async def git_status(repo_path: str) -> Dict[str, Any]:
    """Get git status of a repository."""
    result = await _run_git(["status", "--porcelain"], cwd=repo_path)
    if result["success"]:
        files = [line.strip() for line in result["stdout"].split("\n") if line.strip()]
        result["changed_files"] = files
        result["clean"] = len(files) == 0
    return result


async def git_commit(repo_path: str, message: str, add_all: bool = True) -> Dict[str, Any]:
    """Stage and commit changes."""
    if add_all:
        add_result = await _run_git(["add", "-A"], cwd=repo_path)
        if not add_result["success"]:
            return add_result
    return await _run_git(["commit", "-m", message], cwd=repo_path)


async def git_push(repo_path: str, remote: str = "origin", branch: str = None) -> Dict[str, Any]:
    """Push commits to remote."""
    args = ["push", remote]
    if branch:
        args.append(branch)
    return await _run_git(args, cwd=repo_path)


async def git_pull(repo_path: str, remote: str = "origin", branch: str = None) -> Dict[str, Any]:
    """Pull from remote."""
    args = ["pull", remote]
    if branch:
        args.append(branch)
    return await _run_git(args, cwd=repo_path)


async def git_branch(repo_path: str, name: str = None, checkout: bool = False) -> Dict[str, Any]:
    """List, create, or checkout branches."""
    if name and checkout:
        return await _run_git(["checkout", "-b", name], cwd=repo_path)
    elif name:
        return await _run_git(["branch", name], cwd=repo_path)
    else:
        result = await _run_git(["branch", "-a"], cwd=repo_path)
        if result["success"]:
            result["branches"] = [b.strip().lstrip("* ") for b in result["stdout"].split("\n") if b.strip()]
        return result


async def git_diff(repo_path: str, staged: bool = False) -> Dict[str, Any]:
    """Get git diff."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    return await _run_git(args, cwd=repo_path)


async def git_log(repo_path: str, count: int = 10) -> Dict[str, Any]:
    """Get git log."""
    result = await _run_git(
        ["log", f"-{count}", "--oneline", "--graph", "--decorate"],
        cwd=repo_path,
    )
    if result["success"]:
        result["commits"] = [line.strip() for line in result["stdout"].split("\n") if line.strip()]
    return result
