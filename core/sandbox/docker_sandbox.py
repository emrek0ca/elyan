import subprocess
import json
import logging
import os
from typing import Dict, Any, List, Optional
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("docker_sandbox")

class DockerSandbox:
    """Executes commands in an isolated Docker container."""
    
    def __init__(self, image: str = "python:3.11-slim"):
        self.image = elyan_config.get("sandbox.image", image)
        self.enabled = elyan_config.get("sandbox.enabled", False)
        self.mode = elyan_config.get("sandbox.mode", "restricted") # restricted, full

    def _is_docker_available(self) -> bool:
        try:
            subprocess.run(["docker", "--version"], check=True, capture_output=True)
            return True
        except:
            return False

    async def execute_command(self, command: str, workspace_dir: str = None) -> Dict[str, Any]:
        if not self.enabled or not self._is_docker_available():
            logger.warning("Sandbox disabled or Docker not available. Falling back to host execution (UNSAFE).")
            return await self._execute_host(command, workspace_dir)

        logger.info(f"Executing in Docker sandbox: {command}")
        
        # Build docker run command
        # --rm: remove container after exit
        # -i: interactive for stdin
        # --memory: limit memory
        # --network: restrict network if needed
        
        docker_cmd = [
            "docker", "run", "--rm",
            "-i", # interactive for stdin
            "--memory", "512m",
            "--cpus", "0.5"
        ]
        
        if workspace_dir:
            docker_cmd.extend(["-v", f"{os.path.abspath(workspace_dir)}:/workspace", "-w", "/workspace"])
            
        if self.mode == "restricted":
            docker_cmd.extend(["--network", "none"])

        docker_cmd.extend([self.image, "bash", "-c", command])

        try:
            result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=60)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "sandboxed": True
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out in sandbox", "sandboxed": True}
        except Exception as e:
            return {"success": False, "error": str(e), "sandboxed": True}

    async def _execute_host(self, command: str, workspace_dir: str = None) -> Dict[str, Any]:
        # Fallback host execution (logic from old system) - Patched shell=True
        import shlex
        try:
            safe_cmd = shlex.split(command)
            result = subprocess.run(safe_cmd, capture_output=True, text=True, cwd=workspace_dir, timeout=60)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "sandboxed": False
            }
        except Exception as e:
            return {"success": False, "error": str(e), "sandboxed": False}

# Global instance
docker_sandbox = DockerSandbox()
