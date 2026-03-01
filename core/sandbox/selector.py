"""
Elyan Sandbox Selector — Automatically picks the best available sandbox.

Priority: Docker → Local (sandbox-exec) → Bare subprocess
"""

from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("sandbox_selector")


class SandboxSelector:
    """Smart sandbox selection based on environment capabilities."""

    def __init__(self):
        self._docker = None
        self._local = None

    @property
    def docker(self):
        if self._docker is None:
            from core.sandbox.docker_sandbox import docker_sandbox
            self._docker = docker_sandbox
        return self._docker

    @property
    def local(self):
        if self._local is None:
            from core.sandbox.local_sandbox import local_sandbox
            self._local = local_sandbox
        return self._local

    async def execute(
        self,
        command: str,
        language: str = "shell",
        workspace_dir: Optional[str] = None,
        prefer_docker: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute command in the best available sandbox."""
        if prefer_docker and self.docker.enabled:
            available = await self.docker.check_available_async()
            if available:
                logger.info(f"Using Docker sandbox for: {command[:60]}...")
                return await self.docker.execute(
                    command=command, language=language,
                    workspace_dir=workspace_dir, **kwargs
                )

        logger.info(f"Using local sandbox for: {command[:60]}...")
        return await self.local.execute(
            command=command, workspace_dir=workspace_dir, **kwargs
        )

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        workspace_dir: Optional[str] = None,
        prefer_docker: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute code in the best available sandbox."""
        if prefer_docker and self.docker.enabled:
            available = await self.docker.check_available_async()
            if available:
                logger.info(f"Using Docker sandbox for {language} code execution")
                return await self.docker.execute_code(
                    code=code, language=language,
                    workspace_dir=workspace_dir, **kwargs
                )

        logger.info(f"Using local sandbox for {language} code execution")
        return await self.local.execute_code(
            code=code, language=language,
            workspace_dir=workspace_dir, **kwargs
        )

    async def get_status(self) -> Dict[str, Any]:
        """Get sandbox system status."""
        docker_ok = await self.docker.check_available_async() if self.docker.enabled else False
        return {
            "docker_enabled": self.docker.enabled,
            "docker_available": docker_ok,
            "local_available": True,
            "preferred": "docker" if docker_ok else "local",
        }


# Global instance
sandbox = SandboxSelector()
