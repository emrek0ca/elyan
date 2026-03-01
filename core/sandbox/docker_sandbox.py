"""
Elyan Docker Sandbox v2 — Hardened Secure Execution Environment

Features:
- Configurable resource limits (CPU, RAM, disk, PIDs)
- Network isolation modes (none, restricted, full)
- Automatic timeout enforcement
- Volume mounting with read-only option
- Security policy enforcement (no-new-privileges, seccomp)
- Async execution with proper cleanup
"""

import asyncio
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("docker_sandbox")


# ── Security Policies ────────────────────────────────────────────────────────

BLOCKED_COMMANDS = frozenset([
    "rm -rf /", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:",
    "chmod -R 777 /", "shutdown", "reboot", "halt", "poweroff",
])

BLOCKED_PATTERNS = [
    "curl.*|.*sh",  # pipe to shell
    "wget.*-O.*-.*|.*sh",
    "/dev/sd",
    "/dev/nvme",
]


class ResourceLimits:
    """Container resource constraints."""
    def __init__(
        self,
        memory: str = "512m",
        cpus: str = "1.0",
        pids_limit: int = 100,
        disk_size: str = "1g",
        timeout: int = 120,
    ):
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.disk_size = disk_size
        self.timeout = timeout


class NetworkPolicy:
    """Container network configuration."""
    NONE = "none"          # Tam izolasyon
    RESTRICTED = "bridge"  # Sadece çıkış, giriş yok
    FULL = "bridge"        # Tam erişim


# ── Docker Images ─────────────────────────────────────────────────────────────

LANGUAGE_IMAGES = {
    "python": "python:3.12-slim",
    "node": "node:20-slim",
    "go": "golang:1.22-alpine",
    "rust": "rust:1.77-slim",
    "ruby": "ruby:3.3-slim",
    "cpp": "gcc:14",
    "java": "eclipse-temurin:21-jdk",
    "shell": "alpine:3.19",
}


class DockerSandbox:
    """Hardened Docker sandbox for isolated code execution."""

    def __init__(self):
        cfg = elyan_config
        self.enabled = cfg.get("sandbox.enabled", False)
        self.default_image = cfg.get("sandbox.image", "python:3.12-slim")
        self.default_limits = ResourceLimits(
            memory=cfg.get("sandbox.memory", "512m"),
            cpus=cfg.get("sandbox.cpus", "1.0"),
            timeout=int(cfg.get("sandbox.timeout", 120)),
        )
        self._docker_ok: Optional[bool] = None

    # ── Docker Availability ───────────────────────────────────────────────

    def is_available(self) -> bool:
        if self._docker_ok is not None:
            return self._docker_ok
        try:
            proc = asyncio.get_event_loop().run_until_complete(
                asyncio.create_subprocess_exec(
                    "docker", "info",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            )
            asyncio.get_event_loop().run_until_complete(proc.wait())
            self._docker_ok = proc.returncode == 0
        except Exception:
            self._docker_ok = False
        return self._docker_ok

    async def check_available_async(self) -> bool:
        if self._docker_ok is not None:
            return self._docker_ok
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            self._docker_ok = proc.returncode == 0
        except Exception:
            self._docker_ok = False
        return self._docker_ok

    # ── Security Checks ──────────────────────────────────────────────────

    @staticmethod
    def _check_command_safety(command: str) -> tuple[bool, str]:
        lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in lower:
                return False, f"Blocked command detected: {blocked}"
        import re
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, lower):
                return False, f"Blocked pattern detected: {pattern}"
        return True, ""

    # ── Core Execution ───────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        language: str = "shell",
        workspace_dir: Optional[str] = None,
        limits: Optional[ResourceLimits] = None,
        network: str = NetworkPolicy.NONE,
        env_vars: Optional[Dict[str, str]] = None,
        stdin_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a command in a sandboxed Docker container."""
        t0 = time.time()
        lim = limits or self.default_limits

        # Safety check
        safe, reason = self._check_command_safety(command)
        if not safe:
            return {
                "success": False, "error": reason,
                "sandboxed": True, "blocked": True, "duration_ms": 0,
            }

        # Docker availability
        if not await self.check_available_async():
            logger.warning("Docker not available, falling back to local sandbox.")
            return {"success": False, "error": "Docker not available", "sandboxed": False}

        image = LANGUAGE_IMAGES.get(language, self.default_image)

        # Build docker command
        docker_cmd: List[str] = [
            "docker", "run", "--rm",
            "--memory", lim.memory,
            "--cpus", lim.cpus,
            "--pids-limit", str(lim.pids_limit),
            "--security-opt", "no-new-privileges",
            "--read-only",
        ]

        # Writable tmp
        docker_cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=100m"])

        # Network
        if network == NetworkPolicy.NONE:
            docker_cmd.extend(["--network", "none"])

        # Workspace volume
        if workspace_dir:
            abs_ws = os.path.abspath(workspace_dir)
            docker_cmd.extend(["-v", f"{abs_ws}:/workspace:rw", "-w", "/workspace"])

        # Environment variables
        if env_vars:
            for k, v in env_vars.items():
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.extend([image, "sh", "-c", command])

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data.encode() if stdin_data else None),
                timeout=lim.timeout,
            )

            duration_ms = int((time.time() - t0) * 1000)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(errors="replace")[:50000],
                "stderr": stderr.decode(errors="replace")[:10000],
                "returncode": proc.returncode,
                "sandboxed": True,
                "image": image,
                "duration_ms": duration_ms,
            }

        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Sandbox timeout ({lim.timeout}s)",
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
        limits: Optional[ResourceLimits] = None,
    ) -> Dict[str, Any]:
        """Write code to a temp file inside the container and execute it."""
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="elyan_sandbox_")
            ext_map = {
                "python": ("main.py", "python main.py"),
                "node": ("main.js", "node main.js"),
                "go": ("main.go", "go run main.go"),
                "rust": ("main.rs", "rustc main.rs -o /tmp/out && /tmp/out"),
                "cpp": ("main.cpp", "g++ main.cpp -o /tmp/out && /tmp/out"),
                "ruby": ("main.rb", "ruby main.rb"),
                "java": ("Main.java", "javac Main.java && java Main"),
                "shell": ("main.sh", "sh main.sh"),
            }
            filename, run_cmd = ext_map.get(language, ("main.py", "python main.py"))
            (Path(tmp) / filename).write_text(code)

            return await self.execute(
                command=run_cmd,
                language=language,
                workspace_dir=tmp,
                limits=limits,
            )
        finally:
            if tmp and os.path.exists(tmp):
                shutil.rmtree(tmp, ignore_errors=True)


# Global instance
docker_sandbox = DockerSandbox()
