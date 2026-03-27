from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.mission_control import get_mission_runtime
from core.run_store import get_run_store
from core.storage_paths import resolve_elyan_data_dir
from core.workflow.vertical_runner import get_vertical_workflow_runner


def _now() -> float:
    return time.time()


def _compact(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _default_title(prompt: str, mode: str) -> str:
    excerpt = _compact(prompt)[:72].strip()
    if excerpt:
        return excerpt
    return f"{mode.title()} thread"


def _infer_mode(prompt: str, preferred_mode: str = "") -> str:
    normalized = str(preferred_mode or "").strip().lower()
    if normalized in {"cowork", "document", "presentation", "website"}:
        return normalized
    text = _compact(prompt).lower()
    if any(token in text for token in ("slide", "deck", "presentation", "sunum", "ppt")):
        return "presentation"
    if any(token in text for token in ("website", "landing", "site", "web", "react", "nextjs", "scaffold")):
        return "website"
    if any(token in text for token in ("document", "report", "brief", "proposal", "doc", "pdf", "rapor")):
        return "document"
    return "cowork"


@dataclass
class CoworkTurn:
    turn_id: str
    role: str
    content: str
    created_at: float = field(default_factory=_now)
    mode: str = "cowork"
    status: str = "completed"
    mission_id: str = ""
    run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CoworkTurn":
        return cls(
            turn_id=str(payload.get("turn_id") or f"turn_{uuid.uuid4().hex[:10]}"),
            role=str(payload.get("role") or "user"),
            content=str(payload.get("content") or ""),
            created_at=float(payload.get("created_at") or _now()),
            mode=str(payload.get("mode") or "cowork"),
            status=str(payload.get("status") or "completed"),
            mission_id=str(payload.get("mission_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class CoworkThread:
    thread_id: str
    workspace_id: str
    session_id: str
    title: str
    current_mode: str = "cowork"
    status: str = "queued"
    active_run_id: str = ""
    active_mission_id: str = ""
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    turns: list[CoworkTurn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "title": self.title,
            "current_mode": self.current_mode,
            "status": self.status,
            "active_run_id": self.active_run_id,
            "active_mission_id": self.active_mission_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [turn.to_dict() for turn in self.turns],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CoworkThread":
        return cls(
            thread_id=str(payload.get("thread_id") or f"thread_{uuid.uuid4().hex[:10]}"),
            workspace_id=str(payload.get("workspace_id") or "local-workspace"),
            session_id=str(payload.get("session_id") or "desktop"),
            title=str(payload.get("title") or "Cowork thread"),
            current_mode=str(payload.get("current_mode") or "cowork"),
            status=str(payload.get("status") or "queued"),
            active_run_id=str(payload.get("active_run_id") or ""),
            active_mission_id=str(payload.get("active_mission_id") or ""),
            created_at=float(payload.get("created_at") or _now()),
            updated_at=float(payload.get("updated_at") or _now()),
            turns=[CoworkTurn.from_dict(item) for item in list(payload.get("turns") or []) if isinstance(item, dict)],
            metadata=dict(payload.get("metadata") or {}),
        )


class CoworkThreadStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = Path(storage_path or (resolve_elyan_data_dir() / "cowork" / "threads.json")).expanduser()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._threads: dict[str, CoworkThread] = {}
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            self._threads = {}
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            self._threads = {}
            return
        if not isinstance(payload, dict):
            self._threads = {}
            return
        self._threads = {
            str(thread_id): CoworkThread.from_dict(item)
            for thread_id, item in payload.items()
            if isinstance(item, dict)
        }

    def _save(self) -> None:
        temp_path = self.storage_path.with_suffix(".tmp")
        payload = {thread_id: thread.to_dict() for thread_id, thread in self._threads.items()}
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp_path.replace(self.storage_path)

    async def count_threads(self, *, workspace_id: str) -> int:
        async with self._lock:
            return len([thread for thread in self._threads.values() if thread.workspace_id == workspace_id])

    async def list_threads(self, *, workspace_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            items = [thread for thread in self._threads.values() if not workspace_id or thread.workspace_id == workspace_id]
        items.sort(key=lambda item: float(item.updated_at or 0.0), reverse=True)
        rows: list[dict[str, Any]] = []
        for thread in items[: max(1, int(limit or 20))]:
            rows.append(await self._thread_summary(thread))
        return rows

    async def create_thread(
        self,
        *,
        prompt: str,
        workspace_id: str = "local-workspace",
        session_id: str = "desktop",
        preferred_mode: str = "",
        project_template_id: str = "",
        routing_profile: str = "balanced",
        review_strictness: str = "balanced",
        user_id: str = "",
        agent: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread = CoworkThread(
            thread_id=f"thread_{uuid.uuid4().hex[:10]}",
            workspace_id=str(workspace_id or "local-workspace"),
            session_id=str(session_id or "desktop"),
            title=_default_title(prompt, _infer_mode(prompt, preferred_mode)),
            metadata=dict(metadata or {}),
        )
        async with self._lock:
            self._threads[thread.thread_id] = thread
            self._save()
        return await self.add_turn(
            thread.thread_id,
            prompt=prompt,
            preferred_mode=preferred_mode,
            project_template_id=project_template_id,
            routing_profile=routing_profile,
            review_strictness=review_strictness,
            user_id=user_id or workspace_id,
            agent=agent,
            title=thread.title,
        )

    async def add_turn(
        self,
        thread_id: str,
        *,
        prompt: str,
        preferred_mode: str = "",
        project_template_id: str = "",
        routing_profile: str = "balanced",
        review_strictness: str = "balanced",
        user_id: str = "",
        agent: Any = None,
        title: str = "",
    ) -> dict[str, Any]:
        async with self._lock:
            thread = self._threads.get(str(thread_id or "").strip())
            if thread is None:
                raise KeyError(f"thread not found: {thread_id}")
            normalized_prompt = _compact(prompt)
            if not normalized_prompt:
                raise ValueError("prompt required")
            mode = _infer_mode(normalized_prompt, preferred_mode or thread.current_mode)
            user_turn = CoworkTurn(
                turn_id=f"turn_{uuid.uuid4().hex[:10]}",
                role="user",
                content=normalized_prompt,
                mode=mode,
                metadata={"project_template_id": str(project_template_id or "").strip()},
            )
            thread.turns.append(user_turn)
            thread.current_mode = mode
            thread.status = "queued"
            thread.updated_at = _now()
            if title:
                thread.title = str(title)
            self._save()

        operator_turn = CoworkTurn(
            turn_id=f"turn_{uuid.uuid4().hex[:10]}",
            role="operator",
            content="",
            mode=mode,
            status="running",
            metadata={
                "routing_profile": str(routing_profile or "balanced"),
                "review_strictness": str(review_strictness or "balanced"),
            },
        )

        if mode in {"document", "presentation", "website"}:
            record = await get_vertical_workflow_runner().start_workflow(
                task_type=mode,
                brief=normalized_prompt,
                session_id=thread.session_id,
                title=thread.title,
                project_template_id=str(project_template_id or "").strip(),
                project_name=thread.title,
                routing_profile=str(routing_profile or "balanced"),
                review_strictness=str(review_strictness or "balanced"),
                background=True,
                thread_id=thread.thread_id,
                workspace_id=thread.workspace_id,
            )
            operator_turn.content = f"{mode.title()} lane accepted. Execution started."
            operator_turn.run_id = record.run_id
            async with self._lock:
                thread = self._threads.get(thread.thread_id)
                if thread is None:
                    raise KeyError(f"thread not found: {thread_id}")
                thread.active_run_id = record.run_id
                thread.active_mission_id = ""
                thread.status = str(record.workflow_state or record.status or "received")
                thread.current_mode = mode
                thread.updated_at = _now()
                thread.turns.append(operator_turn)
                self._save()
            return await self.get_thread_detail(thread.thread_id)

        mission = await get_mission_runtime().create_mission(
            normalized_prompt,
            user_id=str(user_id or thread.workspace_id or "local-workspace"),
            channel="desktop",
            mode="Balanced",
            metadata={
                "thread_id": thread.thread_id,
                "workspace_id": thread.workspace_id,
                "session_id": thread.session_id,
                "current_mode": "cowork",
                "routing_profile": str(routing_profile or "balanced"),
                "review_strictness": str(review_strictness or "balanced"),
                "project_template_id": str(project_template_id or "").strip(),
            },
            agent=agent,
            auto_start=True,
        )
        operator_turn.content = "Cowork mission accepted. Planning and execution started."
        operator_turn.mission_id = mission.mission_id

        async with self._lock:
            thread = self._threads.get(thread.thread_id)
            if thread is None:
                raise KeyError(f"thread not found: {thread_id}")
            thread.active_mission_id = mission.mission_id
            thread.active_run_id = ""
            thread.status = mission.status
            thread.current_mode = "cowork"
            thread.updated_at = _now()
            thread.turns.append(operator_turn)
            self._save()
        return await self.get_thread_detail(thread.thread_id)

    async def get_thread(self, thread_id: str) -> CoworkThread | None:
        async with self._lock:
            return self._threads.get(str(thread_id or "").strip())

    async def get_thread_detail(self, thread_id: str) -> dict[str, Any]:
        thread = await self.get_thread(thread_id)
        if thread is None:
            raise KeyError(f"thread not found: {thread_id}")
        run = await get_run_store().get_run(thread.active_run_id) if thread.active_run_id else None
        mission = get_mission_runtime().get_mission(thread.active_mission_id) if thread.active_mission_id else None
        review = dict(run.review_report or {}) if run and isinstance(run.review_report, dict) else {}
        approvals = []
        if mission is not None:
            approvals = [item.to_dict() for item in mission.approvals if item.status == "pending"]

        artifacts: list[dict[str, Any]] = []
        if run is not None:
            for item in list(run.artifacts or []):
                if not isinstance(item, dict):
                    continue
                artifacts.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or item.get("path") or f"artifact_{uuid.uuid4().hex[:8]}"),
                        "label": str(item.get("label") or item.get("path") or "artifact"),
                        "path": str(item.get("path") or ""),
                        "kind": str(item.get("kind") or run.task_type or "artifact"),
                        "run_id": run.run_id,
                        "mission_id": "",
                        "created_at": float(run.completed_at or run.started_at or _now()),
                    }
                )
        if mission is not None:
            for evidence in mission.evidence:
                if not str(evidence.path or "").strip():
                    continue
                artifacts.append(
                    {
                        "artifact_id": str(evidence.evidence_id or evidence.path or f"artifact_{uuid.uuid4().hex[:8]}"),
                        "label": str(evidence.label or evidence.path or "artifact"),
                        "path": str(evidence.path or ""),
                        "kind": str(evidence.kind or "artifact"),
                        "run_id": "",
                        "mission_id": mission.mission_id,
                        "created_at": float(evidence.created_at or _now()),
                    }
                )

        timeline: list[dict[str, Any]] = []
        if run is not None:
            for step in list(run.steps or []):
                if not isinstance(step, dict):
                    continue
                timeline.append(
                    {
                        "id": str(step.get("step_id") or f"step_{uuid.uuid4().hex[:8]}"),
                        "title": str(step.get("name") or "Workflow step"),
                        "status": str(step.get("status") or "unknown"),
                        "source": "run",
                        "created_at": float(step.get("completed_at") or step.get("started_at") or _now()),
                        "error": str(step.get("error") or ""),
                    }
                )
        if mission is not None:
            for event in mission.events:
                timeline.append(
                    {
                        "id": str(event.event_id or f"event_{uuid.uuid4().hex[:8]}"),
                        "title": str(event.label or event.event_type or "Mission event"),
                        "status": str(event.status or event.event_type or "unknown"),
                        "source": "mission",
                        "created_at": float(event.created_at or _now()),
                        "error": "",
                    }
                )
        timeline.sort(key=lambda item: float(item.get("created_at") or 0.0))

        dynamic_operator_turns: list[dict[str, Any]] = []
        if run is not None:
            dynamic_operator_turns.append(
                {
                    "turn_id": f"turn_dynamic_run_{run.run_id}",
                    "role": "operator",
                    "content": str(run.error or (review.get("recommended_action") if review else "") or run.intent or "Run in progress"),
                    "created_at": float(run.completed_at or run.started_at or _now()),
                    "mode": str(run.task_type or thread.current_mode or "cowork"),
                    "status": str(run.workflow_state or run.status or "running"),
                    "mission_id": "",
                    "run_id": run.run_id,
                    "metadata": {
                        "review_status": str(review.get("status") or ""),
                        "artifact_count": len(artifacts),
                    },
                }
            )
        elif mission is not None and str(mission.deliverable or "").strip():
            dynamic_operator_turns.append(
                {
                    "turn_id": f"turn_dynamic_mission_{mission.mission_id}",
                    "role": "operator",
                    "content": str(mission.deliverable or ""),
                    "created_at": float(mission.updated_at or _now()),
                    "mode": "cowork",
                    "status": mission.status,
                    "mission_id": mission.mission_id,
                    "run_id": "",
                    "metadata": {
                        "quality_status": str(mission.control_summary().get("quality_status") or ""),
                    },
                }
            )

        turns = [turn.to_dict() for turn in thread.turns] + dynamic_operator_turns
        turns.sort(key=lambda item: float(item.get("created_at") or 0.0))
        return {
            "thread_id": thread.thread_id,
            "workspace_id": thread.workspace_id,
            "session_id": thread.session_id,
            "title": thread.title,
            "current_mode": thread.current_mode,
            "status": str((run.workflow_state if run else mission.status if mission else thread.status) or thread.status),
            "active_run_id": thread.active_run_id,
            "active_mission_id": thread.active_mission_id,
            "pending_approvals": approvals,
            "artifacts": artifacts,
            "review_status": str(review.get("status") or (mission.control_summary().get("review_status") if mission else "") or ""),
            "last_user_turn": next((turn for turn in reversed(turns) if str(turn.get("role") or "") == "user"), None),
            "last_operator_turn": next((turn for turn in reversed(turns) if str(turn.get("role") or "") == "operator"), None),
            "turns": turns,
            "timeline": timeline[-40:],
            "created_at": thread.created_at,
            "updated_at": max(
                float(thread.updated_at or 0.0),
                float(run.completed_at or run.started_at or 0.0) if run else 0.0,
                float(mission.updated_at or 0.0) if mission else 0.0,
            ),
            "lane_summary": {
                "mode": thread.current_mode,
                "run_state": str(run.workflow_state or run.status or "") if run else "",
                "mission_state": str(mission.status or "") if mission else "",
                "assigned_agents": list(run.assigned_agents or []) if run else [],
                "review": review,
            },
            "metadata": dict(thread.metadata or {}),
        }

    async def home_snapshot(self, *, workspace_id: str = "local-workspace", limit: int = 8) -> dict[str, Any]:
        threads = await self.list_threads(workspace_id=workspace_id, limit=limit)
        last_thread = threads[0] if threads else None
        return {
            "workspace_id": workspace_id,
            "recent_threads": threads,
            "last_thread": last_thread,
            "active_count": len([thread for thread in threads if str(thread.get("status") or "") not in {"completed", "failed"}]),
        }

    async def _thread_summary(self, thread: CoworkThread) -> dict[str, Any]:
        detail = await self.get_thread_detail(thread.thread_id)
        return {
            "thread_id": thread.thread_id,
            "workspace_id": thread.workspace_id,
            "session_id": thread.session_id,
            "title": thread.title,
            "current_mode": detail.get("current_mode") or thread.current_mode,
            "status": detail.get("status") or thread.status,
            "active_run_id": detail.get("active_run_id") or thread.active_run_id,
            "active_mission_id": detail.get("active_mission_id") or thread.active_mission_id,
            "pending_approvals": len(list(detail.get("pending_approvals") or [])),
            "artifact_count": len(list(detail.get("artifacts") or [])),
            "review_status": str(detail.get("review_status") or ""),
            "last_user_turn": detail.get("last_user_turn"),
            "last_operator_turn": detail.get("last_operator_turn"),
            "updated_at": float(detail.get("updated_at") or thread.updated_at or _now()),
            "created_at": thread.created_at,
        }


_thread_store: CoworkThreadStore | None = None


def get_cowork_thread_store(storage_path: Path | None = None) -> CoworkThreadStore:
    global _thread_store
    if _thread_store is None:
        _thread_store = CoworkThreadStore(storage_path=storage_path)
    return _thread_store


__all__ = [
    "CoworkThread",
    "CoworkThreadStore",
    "CoworkTurn",
    "get_cowork_thread_store",
]
