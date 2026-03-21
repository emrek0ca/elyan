from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from .isolation import IsolationProfile, sanitized_volumes, zero_permission_profile
from .policy import SandboxConfig, merge_sandbox_config, sandbox_config_for_action

logger = get_logger("elyan.sandbox")

try:
    import docker  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    docker = None


class SandboxExecutor:
    def __init__(self, *, prefer_docker: bool = True) -> None:
        self.prefer_docker = bool(prefer_docker)
        self._client = None
        self._docker_available: bool | None = None
        if docker is not None:
            try:
                self._client = docker.from_env()
                self._docker_available = bool(self._client.ping())
            except Exception:
                self._client = None
                self._docker_available = False

    def available(self) -> bool:
        if self._docker_available is not None:
            return bool(self._docker_available)
        docker_bin = shutil.which("docker")
        if docker_bin is None:
            self._docker_available = False
            return False
        try:
            probe = subprocess.run(
                [docker_bin, "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            self._docker_available = probe.returncode == 0
            return bool(self._docker_available)
        except Exception:
            self._docker_available = False
            return False

    def _materialize(self, code_or_command: str, config: SandboxConfig) -> tuple[SandboxConfig, str, str | None]:
        payload = merge_sandbox_config(config)
        command = str(payload.command or code_or_command or "").strip()
        temp_dir: str | None = None

        language = str(payload.language or "shell").strip().lower() or "shell"
        if language in {"python", "javascript"} and code_or_command:
            temp_dir = tempfile.mkdtemp(prefix="elyan_sandbox_")
            script_name = "main.py" if language == "python" else "main.js"
            script_path = Path(temp_dir) / script_name
            script_path.write_text(str(code_or_command), encoding="utf-8")
            volumes = dict(payload.volumes or {})
            volumes[str(Path(temp_dir).resolve())] = payload.working_dir or "/workspace"
            payload = payload.model_copy(update={"volumes": volumes, "command": command or {"python": "python main.py", "javascript": "node main.js"}[language]})
        elif not command:
            command = str(code_or_command or "").strip()

        if not command:
            raise ValueError("Sandbox command is empty")
        return payload, command, temp_dir

    @staticmethod
    def _normalize_result(
        *,
        backend: str,
        config: SandboxConfig,
        command: str,
        raw: dict[str, Any] | None,
        duration_ms: int,
        script_path: str = "",
    ) -> dict[str, Any]:
        payload = dict(raw or {})
        stdout = str(payload.get("stdout") or payload.get("output") or payload.get("logs") or "")
        stderr = str(payload.get("stderr") or payload.get("error") or "")
        return_code = payload.get("return_code", payload.get("exit_code", payload.get("returncode", 0)))
        try:
            return_code = int(return_code)
        except Exception:
            return_code = 0 if payload.get("success") else 1
        success = bool(payload.get("success", return_code == 0))
        status = str(payload.get("status") or ("success" if success else "failed"))
        result = {
            "success": success,
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "return_code": return_code,
            "duration_ms": int(duration_ms),
            "backend": backend,
            "sandboxed": True,
            "image": str(config.image or ""),
            "language": str(config.language or "shell"),
            "command": command,
            "working_dir": str(config.working_dir or "/workspace"),
        }
        if script_path:
            result["script_path"] = script_path
        if payload.get("artifacts") is not None:
            result["artifacts"] = payload.get("artifacts")
        if payload.get("message") is not None:
            result["message"] = str(payload.get("message") or "")
        if payload.get("error") is not None and not result["stderr"]:
            result["stderr"] = str(payload.get("error") or "")
        if payload.get("warnings") is not None:
            result["warnings"] = payload.get("warnings")
        return result

    def _run_with_sdk(self, command: str, config: SandboxConfig, timeout: int) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Docker SDK unavailable")
        tmpfs = {entry: "" for entry in list(config.tmpfs or []) if str(entry).strip()}
        container = None
        start = time.perf_counter()
        try:
            container = self._client.containers.run(
                image=str(config.image or "python:3.12-slim"),
                command=["sh", "-lc", command],
                detach=True,
                mem_limit=str(config.memory_limit or "512m"),
                cpu_period=100000,
                cpu_quota=max(1, int(float(config.cpu_limit or 0.5) * 100000)),
                pids_limit=int(config.pids_limit or 64),
                network_mode="bridge" if bool(config.network) else "none",
                volumes=sanitized_volumes(config),
                working_dir=str(config.working_dir or "/workspace"),
                read_only=bool(config.read_only),
                user=str(config.user or "nobody"),
                cap_drop=list(config.cap_drop or ["ALL"]),
                security_opt=list(config.security_opt or ["no-new-privileges"]),
                environment=dict(config.env or {}),
                tmpfs=tmpfs,
            )
            while True:
                container.reload()
                status = str(getattr(container, "status", "") or "").lower()
                if status in {"exited", "dead"}:
                    break
                if (time.perf_counter() - start) >= max(1, int(timeout or 30)):
                    try:
                        container.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.2)
            wait_result = {}
            try:
                wait_result = container.wait(timeout=1)
            except Exception:
                pass
            logs = ""
            try:
                logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            except Exception:
                pass
            raw = {
                "success": int(wait_result.get("StatusCode", 1) or 1) == 0,
                "stdout": logs,
                "stderr": "",
                "return_code": int(wait_result.get("StatusCode", 1) or 1),
            }
            return self._normalize_result(
                backend="docker-sdk",
                config=config,
                command=command,
                raw=raw,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    async def _run_with_cli(self, command: str, config: SandboxConfig, timeout: int) -> dict[str, Any]:
        start = time.perf_counter()
        docker_bin = shutil.which("docker")
        if not docker_bin:
            raise RuntimeError("Docker CLI unavailable")
        args = [
            docker_bin,
            "run",
            "--rm",
            "--memory",
            str(config.memory_limit or "512m"),
            "--cpus",
            str(float(config.cpu_limit or 0.5)),
            "--pids-limit",
            str(int(config.pids_limit or 64)),
            "--network",
            "bridge" if bool(config.network) else "none",
            "--user",
            str(config.user or "nobody"),
        ]
        if bool(config.read_only):
            args.append("--read-only")
        for item in list(config.cap_drop or ["ALL"]):
            if str(item).strip():
                args.extend(["--cap-drop", str(item).strip()])
        for item in list(config.security_opt or ["no-new-privileges"]):
            if str(item).strip():
                args.extend(["--security-opt", str(item).strip()])
        for host_path, container_path in sanitized_volumes(config).items():
            args.extend(["-v", f"{host_path}:{container_path}:rw"])
        for item in list(config.tmpfs or ["/tmp"]):
            if str(item).strip():
                args.extend(["--tmpfs", str(item).strip()])
        for key, value in dict(config.env or {}).items():
            args.extend(["-e", f"{key}={value}"])
        args.extend([
            "-w",
            str(config.working_dir or "/workspace"),
            str(config.image or "python:3.12-slim"),
            "sh",
            "-lc",
            command,
        ])

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(1, int(timeout or 30)))
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            stdout, stderr = b"", b""
        result = {
            "success": proc.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "return_code": proc.returncode if proc.returncode is not None else 1,
        }
        return self._normalize_result(
            backend="docker-cli",
            config=config,
            command=command,
            raw=result,
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    async def _run_legacy(self, command: str, config: SandboxConfig, timeout: int) -> dict[str, Any]:
        from core.sandbox.local_sandbox import local_sandbox

        workspace_dir = ""
        for host_path, container_path in sanitized_volumes(config).items():
            if str(container_path).strip() == "/workspace":
                workspace_dir = str(host_path)
                break
        legacy_config = config.model_copy(update={"working_dir": workspace_dir}) if workspace_dir else config
        result = await local_sandbox.execute(
            command=command,
            workspace_dir=workspace_dir or None,
            env_vars=dict(legacy_config.env or {}),
            timeout=max(1, int(timeout or legacy_config.timeout or 30)),
        )
        return self._normalize_result(
            backend="legacy-sandbox",
            config=legacy_config,
            command=command,
            raw=result,
            duration_ms=int(result.get("duration_ms") or 0),
        )

    async def run(self, code_or_command: str, config: SandboxConfig | dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        cfg = merge_sandbox_config(config or {}) if config is not None else SandboxConfig()
        cfg, command, temp_dir = self._materialize(code_or_command, cfg)
        try:
            docker_ready = self.available()
            if self.prefer_docker and self._client is not None and docker_ready:
                return await asyncio.to_thread(self._run_with_sdk, command, cfg, timeout)
            if docker_ready and shutil.which("docker") is not None:
                return await self._run_with_cli(command, cfg, timeout)
            return await self._run_legacy(command, cfg, timeout)
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)


_sandbox_executor: SandboxExecutor | None = None


def get_sandbox_executor() -> SandboxExecutor:
    global _sandbox_executor
    if _sandbox_executor is None:
        _sandbox_executor = SandboxExecutor()
    return _sandbox_executor


sandbox_executor = get_sandbox_executor()
