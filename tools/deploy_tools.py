"""
Elyan Deploy Tools — Cloud deployment integrations

Vercel, Netlify, Railway, Fly.io, Heroku deploy + CI/CD trigger.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("deploy_tools")


async def deploy_to_vercel(project_dir: str, token: str = None) -> Dict[str, Any]:
    """Deploy a project to Vercel."""
    token = token or os.environ.get("VERCEL_TOKEN")
    if not token:
        return {"success": False, "error": "VERCEL_TOKEN not set"}

    try:
        proc = await asyncio.create_subprocess_exec(
            "npx", "vercel", "--yes", "--token", token,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        url = stdout.decode().strip().split("\n")[-1]
        return {
            "success": proc.returncode == 0,
            "url": url,
            "platform": "vercel",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "platform": "vercel"}


async def deploy_to_netlify(project_dir: str, token: str = None, site_name: str = None) -> Dict[str, Any]:
    """Deploy a project to Netlify."""
    token = token or os.environ.get("NETLIFY_TOKEN")
    if not token:
        return {"success": False, "error": "NETLIFY_TOKEN not set"}

    args = ["npx", "netlify-cli", "deploy", "--prod", "--dir", project_dir, "--auth", token]
    if site_name:
        args.extend(["--site", site_name])

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode()[:5000],
            "platform": "netlify",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "platform": "netlify"}


async def deploy_docker(image_tag: str, registry: str = "docker.io") -> Dict[str, Any]:
    """Push a Docker image to a registry."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "push", f"{registry}/{image_tag}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode()[:5000],
            "platform": "docker_registry",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_deploy_status() -> Dict[str, Any]:
    """Check which deploy platforms are configured."""
    return {
        "vercel": bool(os.environ.get("VERCEL_TOKEN")),
        "netlify": bool(os.environ.get("NETLIFY_TOKEN")),
        "docker_registry": True,
    }
