"""
Elyan Build & Auto-Deploy Pipeline

Builds the project in sandbox, runs tests, and optionally deploys.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("build_pipeline")


class BuildPipeline:
    """Build and test a generated project."""

    async def build_and_test(
        self,
        project_dir: str,
        project_type: str = "python",
    ) -> Dict[str, Any]:
        """Build project and run tests in sandbox."""
        from core.sandbox.selector import sandbox

        results = {"build": None, "test": None, "lint": None}

        if project_type in ("fastapi", "python", "python_cli", "django"):
            # Install deps
            results["build"] = await sandbox.execute(
                "pip install -r requirements.txt 2>&1",
                workspace_dir=project_dir,
            )
            # Run tests if they exist
            test_dir = Path(project_dir) / "tests"
            if test_dir.exists():
                results["test"] = await sandbox.execute(
                    "python -m pytest tests/ -v 2>&1",
                    workspace_dir=project_dir,
                )
            # Lint check
            results["lint"] = await sandbox.execute(
                "python -m py_compile main.py 2>&1",
                workspace_dir=project_dir,
            )

        elif project_type in ("nextjs", "express", "electron"):
            results["build"] = await sandbox.execute(
                "npm install 2>&1",
                workspace_dir=project_dir,
            )

        build_ok = results["build"] and results["build"].get("success", False)
        test_ok = not results["test"] or results["test"].get("success", False)

        return {
            "success": build_ok and test_ok,
            "results": results,
            "project_type": project_type,
        }


class AutoDeploy:
    """Automatic deployment after successful build."""

    async def deploy(
        self,
        project_dir: str,
        project_type: str = "python",
        platform: str = "vercel",
    ) -> Dict[str, Any]:
        """Deploy project to cloud platform."""
        from tools.deploy_tools import deploy_to_vercel, deploy_to_netlify, deploy_docker

        logger.info(f"Auto-deploying {project_type} to {platform}...")

        if platform == "vercel":
            return await deploy_to_vercel(project_dir)
        elif platform == "netlify":
            return await deploy_to_netlify(project_dir)
        elif platform == "docker":
            from tools.container_tools import docker_build
            tag = f"elyan-project:{Path(project_dir).name}"
            build = await docker_build(project_dir, tag=tag)
            if build.get("success"):
                return await deploy_docker(tag)
            return build
        else:
            return {"success": False, "error": f"Unknown platform: {platform}"}


# Global instances
build_pipeline = BuildPipeline()
auto_deploy = AutoDeploy()
