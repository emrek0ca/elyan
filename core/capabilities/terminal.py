import asyncio
import os
import pathlib
from typing import Any, Dict, List

from core.execution_guard import get_execution_guard
from core.observability.logger import get_structured_logger

slog = get_structured_logger("capability_terminal")


def _identity_from_metadata(metadata: dict[str, Any] | None = None) -> dict[str, str]:
    payload = metadata if isinstance(metadata, dict) else {}
    nested = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "workspace_id": str(payload.get("workspace_id") or nested.get("workspace_id") or "local-workspace").strip() or "local-workspace",
        "session_id": str(payload.get("session_id") or nested.get("session_id") or "").strip(),
        "run_id": str(payload.get("run_id") or nested.get("run_id") or "").strip(),
        "actor_id": str(payload.get("actor_id") or payload.get("user_id") or nested.get("actor_id") or nested.get("user_id") or "").strip(),
    }


def _observe_terminal_runtime(
    *,
    success: bool,
    metadata: dict[str, Any] | None = None,
    reason: str = "",
    extra: dict[str, Any] | None = None,
    latency_ms: float = 0.0,
    tool_name: str = "execute",
) -> None:
    identity = _identity_from_metadata(metadata)
    verification = {
        "status": "success" if success else "failed",
        "ok": bool(success),
        "failed_codes": [] if success else ["terminal_execution_failed"],
    }
    get_execution_guard().observe_capability_runtime(
        capability="terminal",
        action="execute",
        success=bool(success),
        workspace_id=identity["workspace_id"],
        actor_id=identity["actor_id"],
        session_id=identity["session_id"],
        run_id=identity["run_id"],
        reason=str(reason or "").strip(),
        verification=verification,
        metadata=dict(extra or {}),
        level="info" if success else "warning",
    )
    try:
        from core.learning.reward_shaper import RewardShaper
        from core.learning.tool_bandit import get_tool_bandit

        reward = RewardShaper().compute_reward(
            task_completed=success,
            user_explicit_feedback=None,
            response_time_ms=float(latency_ms or 0.0),
            approval_required=False,
            task_was_in_cache=False,
            error_occurred=not success,
        )
        get_tool_bandit().record_outcome(
            task_category="terminal",
            tool_name=str(tool_name or "execute").strip() or "execute",
            success=success,
            latency_ms=float(latency_ms or 0.0),
            user_satisfaction=max(0.0, (reward + 2.0) / 4.0),
        )
    except Exception:
        pass


class TerminalCapability:
    """
    Implements controlled terminal execution according to ADR-008.
    """

    def __init__(self, allowed_cwd: List[str] = None):
        self.allowed_cwd = allowed_cwd or [str(pathlib.Path.home())]

    def _is_safe_cwd(self, cwd: str) -> bool:
        resolved = pathlib.Path(cwd).expanduser().resolve()
        for root in self.allowed_cwd:
            if str(resolved).startswith(str(pathlib.Path(root).expanduser().resolve())):
                return True
        return False

    async def execute(
        self,
        command: str,
        cwd: str = None,
        timeout: int = 30,
        metadata: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Executes a command in a subprocess with timeout and capture."""
        target_cwd = cwd or str(pathlib.Path.cwd())

        if not self._is_safe_cwd(target_cwd):
            _observe_terminal_runtime(
                success=False,
                metadata=metadata,
                reason=f"CWD not allowed: {target_cwd}",
                extra={"cwd": str(target_cwd), "command": str(command or "")},
            )
            raise PermissionError(f"CWD not allowed: {target_cwd}")

        slog.log_event("command_execution_started", {"command": command, "cwd": target_cwd})
        started_at = asyncio.get_running_loop().time()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=target_cwd,
                env=self._get_safe_env(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                exit_code = int(process.returncode or 0)
                result = {
                    "exit_code": exit_code,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                }

                slog.log_event(
                    "command_execution_finished",
                    {
                        "command": command,
                        "exit_code": exit_code,
                        "has_stderr": bool(stderr),
                    },
                )
                _observe_terminal_runtime(
                    success=exit_code == 0,
                    metadata=metadata,
                    reason="" if exit_code == 0 else f"exit_code:{exit_code}",
                    extra={
                        "cwd": str(target_cwd),
                        "command": str(command or ""),
                        "exit_code": exit_code,
                        "has_stderr": bool(stderr),
                    },
                    latency_ms=(asyncio.get_running_loop().time() - started_at) * 1000.0,
                    tool_name="execute",
                )
                return result

            except asyncio.TimeoutError:
                process.kill()
                slog.log_event("command_execution_timeout", {"command": command}, level="warning")
                payload = {"error": "timeout", "exit_code": -1}
                _observe_terminal_runtime(
                    success=False,
                    metadata=metadata,
                    reason="timeout",
                    extra={"cwd": str(target_cwd), "command": str(command or ""), "timeout": int(timeout or 0)},
                    latency_ms=(asyncio.get_running_loop().time() - started_at) * 1000.0,
                    tool_name="execute",
                )
                return payload

        except Exception as exc:
            slog.log_event("command_execution_error", {"command": command, "error": str(exc)}, level="error")
            _observe_terminal_runtime(
                success=False,
                metadata=metadata,
                reason=str(exc),
                extra={"cwd": str(target_cwd), "command": str(command or "")},
                latency_ms=(asyncio.get_running_loop().time() - started_at) * 1000.0,
                tool_name="execute",
            )
            return {"error": str(exc), "exit_code": 1}

    def _get_safe_env(self) -> Dict[str, str]:
        """Returns a sanitized environment for subprocesses."""
        safe_keys = {"PATH", "TERM", "LANG", "LC_ALL", "USER", "HOME", "SHELL"}
        env = {k: v for k, v in os.environ.items() if k in safe_keys or k.startswith("ELYAN_")}
        return env


# Global instance
terminal_capability = TerminalCapability()
