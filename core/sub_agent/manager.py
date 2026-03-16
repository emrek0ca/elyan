from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import existing_text_path
from core.workspace_contract import ensure_workspace_contract

from .executor import SubAgentExecutor
from .session import SessionState, SubAgentResult, SubAgentSession, SubAgentTask
from .validator import SubAgentValidator


class SubAgentManager:
    """Lifecycle manager for isolated sub-agent sessions."""

    def __init__(
        self,
        agent: Any,
        *,
        parent_session_id: str = "root",
        tool_scopes: Optional[Dict[str, Iterable[str]]] = None,
        max_iterations: int = 5,
        max_validation_retries: int = 2,
    ):
        self.agent = agent
        self.parent_session_id = str(parent_session_id or "root")
        self.tool_scopes = {
            str(k): frozenset(str(x) for x in (v or []))
            for k, v in dict(tool_scopes or {}).items()
        }
        self.executor = SubAgentExecutor(agent, max_iterations=max_iterations)
        self.validator = SubAgentValidator()
        self.max_validation_retries = max(0, min(5, int(max_validation_retries or 0)))
        self._sessions: Dict[str, SubAgentSession] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._workspace_root = (resolve_elyan_data_dir() / "subagents").resolve()

    def _new_session_id(self) -> str:
        return f"agent:{self.parent_session_id}:subagent:{uuid.uuid4().hex[:10]}"

    def _build_workspace(self, run_id: str, specialist_key: str, allowed_tools: frozenset[str]) -> tuple[str, str]:
        safe_id = str(run_id).replace(":", "_")
        base = (self._workspace_root / safe_id).resolve()
        contract_files = ensure_workspace_contract(
            base,
            role=f"sub-agent:{specialist_key}",
            allowed_tools=list(allowed_tools),
            metadata={"parent_session": self.parent_session_id, "specialist": specialist_key, "run_id": run_id},
        )
        memory_path = contract_files.get("MEMORY.txt", str(existing_text_path(base / "MEMORY.md").resolve()))
        return str(base), str(memory_path)

    async def spawn(self, specialist_key: str, task: SubAgentTask, tools=None) -> str:
        run_id = self._new_session_id()
        allowed_tools = frozenset(str(x) for x in (tools or self.tool_scopes.get(specialist_key, [])))
        if not task.objective:
            task.objective = str(task.description or task.name or "").strip()
        if not task.success_criteria:
            task.success_criteria = ["izinli tool ile somut çıktı üret", "boş sonuç döndürme", "başarısızsa nedenini yaz"]
        workspace_path, memory_path = self._build_workspace(run_id, str(specialist_key or "general"), allowed_tools)
        session = SubAgentSession(
            session_id=run_id,
            parent_session_id=self.parent_session_id,
            specialist_key=str(specialist_key or "general"),
            task=task,
            allowed_tools=allowed_tools,
            workspace_path=workspace_path,
            memory_path=memory_path,
            auth_profile="isolated",
            can_spawn=False,
        )
        self._sessions[run_id] = session
        self._events[run_id] = asyncio.Event()

        async def _run() -> None:
            try:
                task_gates = list(getattr(session.task, "gates", []) or [])
                if task_gates:
                    result, validation = await self.validator.validate_and_retry(
                        self.executor,
                        session,
                        task_gates,
                        max_retries=self.max_validation_retries,
                    )
                    if not validation.passed:
                        result = SubAgentResult(
                            status="failed",
                            result={
                                "success": False,
                                "error": "validation_failed",
                                "failed_gates": list(validation.failed_gates),
                                "issues": list(validation.issues),
                                "raw_result": result.result,
                            },
                            notes=[*(result.notes or []), f"validation_failed:{','.join(validation.failed_gates)}"],
                            artifacts=list(result.artifacts or []),
                            execution_time_ms=int(result.execution_time_ms or 0),
                            token_usage=dict(result.token_usage or {}),
                        )
                        session.state = SessionState.FAILED
                else:
                    result = await self.executor.run(session)
                session.result = result
                if session.state not in {SessionState.COMPLETED, SessionState.FAILED}:
                    session.state = SessionState.COMPLETED
            except Exception as exc:
                session.state = SessionState.FAILED
                session.result = SubAgentResult(
                    status="failed",
                    result={"success": False, "error": str(exc)},
                    notes=["manager_exception"],
                    artifacts=[],
                    execution_time_ms=0,
                    token_usage={"prompt": 0, "completion": 0, "cost_usd": 0.0},
                )
            finally:
                session.completed_at = time.time()
                self._events[run_id].set()

        self._tasks[run_id] = asyncio.create_task(_run(), name=f"sub-agent:{run_id}")
        return run_id

    async def get_result(self, run_id: str, timeout: int = 60) -> SubAgentResult:
        rid = str(run_id or "")
        if rid not in self._sessions:
            raise KeyError(f"Unknown sub-agent run_id: {rid}")
        event = self._events[rid]
        await asyncio.wait_for(event.wait(), timeout=max(1, int(timeout or 60)))
        result = self._sessions[rid].result
        if result is None:
            raise RuntimeError(f"Sub-agent finished without result: {rid}")
        return result

    async def spawn_and_wait(
        self,
        specialist_key: str,
        task: SubAgentTask,
        timeout: int = 300,
        tools=None,
    ) -> SubAgentResult:
        run_id = await self.spawn(specialist_key, task, tools=tools)
        return await self.get_result(run_id, timeout=timeout)

    async def spawn_parallel(
        self,
        tasks: List[Tuple[str, SubAgentTask]],
        timeout: int = 300,
    ) -> List[SubAgentResult]:
        run_ids = []
        for specialist, task in list(tasks or []):
            run_ids.append(await self.spawn(specialist, task))

        async def _collect(rid: str) -> SubAgentResult:
            return await self.get_result(rid, timeout=timeout)

        return list(await asyncio.gather(*[_collect(rid) for rid in run_ids]))


__all__ = ["SubAgentManager"]
