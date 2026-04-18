from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from core.sandbox.docker_sandbox import DockerSandbox, NetworkPolicy, ResourceLimits
from utils.logger import get_logger

logger = get_logger("sandbox.runtime")


class SandboxRuntime:
    """File-backed runtime façade over the hardened Docker sandbox."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        docker: DockerSandbox | None = None,
        default_limits: ResourceLimits | None = None,
    ) -> None:
        self._docker = docker or DockerSandbox()
        self._workspace_owner = workspace_root is None
        self._workspace_root = Path(workspace_root or tempfile.mkdtemp(prefix="elyan_runtime_")).expanduser().resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self.default_limits = default_limits or ResourceLimits(
            memory="2g",
            cpus="2.0",
            pids_limit=128,
            disk_size="2g",
            timeout=60,
        )

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def stage_workspace(self, source: str | Path) -> Path:
        """Mirror a source directory into the runtime workspace."""

        source_path = Path(source).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))

        self._reset_workspace()
        if source_path.is_file():
            target = self._workspace_root / source_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            return self._workspace_root

        for entry in source_path.iterdir():
            destination = self._workspace_root / entry.name
            if entry.is_dir():
                shutil.copytree(entry, destination, dirs_exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, destination)
        return self._workspace_root

    def write_file(self, relative_path: str | Path, content: str) -> Path:
        target = self._resolve_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return target

    def read_file(self, relative_path: str | Path) -> str:
        target = self._resolve_path(relative_path)
        return target.read_text(encoding="utf-8")

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        workspace_dir: str | Path | None = None,
        limits: ResourceLimits | None = None,
        timeout: int | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute code in a staged workspace with strict sandbox defaults."""

        run_dir = self._prepare_run_directory(workspace_dir)
        filename, command = self._language_command(language)
        (run_dir / filename).write_text(code, encoding="utf-8")

        limits = limits or self.default_limits
        if timeout is not None:
            limits = ResourceLimits(
                memory=limits.memory,
                cpus=limits.cpus,
                pids_limit=limits.pids_limit,
                disk_size=limits.disk_size,
                timeout=int(timeout),
            )

        result = await self._docker.execute(
            command=command,
            language=language,
            workspace_dir=str(run_dir),
            limits=limits,
            network=NetworkPolicy.NONE,
            env_vars=env_vars,
        )
        return result

    def close(self) -> None:
        if self._workspace_owner:
            shutil.rmtree(self._workspace_root, ignore_errors=True)

    def _prepare_run_directory(self, workspace_dir: str | Path | None) -> Path:
        base = self._workspace_root / ".runs" / uuid.uuid4().hex
        base.mkdir(parents=True, exist_ok=True)
        if workspace_dir is not None:
            source = Path(workspace_dir).expanduser().resolve()
            if source.exists():
                if source.is_dir():
                    shutil.copytree(source, base, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, base / source.name)
        return base

    def _resolve_path(self, relative_path: str | Path) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("path must be relative to the workspace root")
        resolved = (self._workspace_root / candidate).resolve()
        root = self._workspace_root.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("path escapes the workspace root")
        return resolved

    def _reset_workspace(self) -> None:
        for entry in self._workspace_root.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    @staticmethod
    def _language_command(language: str) -> tuple[str, str]:
        mapping = {
            "python": ("main.py", "python main.py"),
            "node": ("main.js", "node main.js"),
            "go": ("main.go", "go run main.go"),
            "rust": ("main.rs", "rustc main.rs -o /tmp/out && /tmp/out"),
            "cpp": ("main.cpp", "g++ main.cpp -o /tmp/out && /tmp/out"),
            "ruby": ("main.rb", "ruby main.rb"),
            "java": ("Main.java", "javac Main.java && java Main"),
            "shell": ("main.sh", "sh main.sh"),
        }
        return mapping.get(language, ("main.py", "python main.py"))


docker_runtime = SandboxRuntime()


__all__ = ["SandboxRuntime", "NetworkPolicy", "docker_runtime"]
