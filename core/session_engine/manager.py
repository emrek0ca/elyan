import asyncio
import uuid
from typing import Dict, Optional, Callable, Awaitable, Any
from core.protocol.events import BaseEvent, MessageReceived
from .lane import SessionLane, QueuePolicy
from utils.logger import get_logger
from core.observability.logger import get_structured_logger

logger = get_logger("session_manager")
slog = get_structured_logger("session_manager")

class SessionManager:
    """
    Manages all active session lanes. 
    Routes incoming events to the correct lane and triggers the scheduler.
    """
    def __init__(self):
        self._lanes: Dict[str, SessionLane] = {}
        self._lock = asyncio.Lock()
        self._executor_callback: Optional[Callable[[BaseEvent], Awaitable[Any]]] = None

    def set_executor(self, callback: Callable[[BaseEvent], Awaitable[Any]]):
        """Sets the function to call when an event is popped from the queue."""
        self._executor_callback = callback

    async def get_or_create_lane(self, session_id: str) -> SessionLane:
        async with self._lock:
            if session_id not in self._lanes:
                self._lanes[session_id] = SessionLane(session_id)
                slog.log_event("session_created", {"session_id": session_id}, session_id=session_id)
            return self._lanes[session_id]

    async def resolve_session_id(self, event: BaseEvent) -> str:
        """
        Determines the session ID for a given event.
        """
        if hasattr(event, "session_id") and getattr(event, "session_id"):
            return getattr(event, "session_id")
            
        if isinstance(event, MessageReceived):
            return f"sess_{event.channel}_{event.user_id}"
            
        return "sess_default"

    async def dispatch_event(self, event: BaseEvent, policy: str = QueuePolicy.FOLLOWUP):
        """
        Main entry point for events into the Session Engine.
        """
        session_id = await self.resolve_session_id(event)
        lane = await self.get_or_create_lane(session_id)
        
        slog.log_event("event_dispatched", {
            "event_id": event.event_id,
            "policy": policy,
            "type": event.__class__.__name__
        }, session_id=session_id)
        
        await lane.enqueue(event, policy=policy)
        asyncio.create_task(self._trigger_scheduler(lane))

    async def _trigger_scheduler(self, lane: SessionLane):
        """
        Checks if the lane is free and has pending events. If so, starts a run.
        """
        if lane.is_locked:
            return

        next_event = lane.pop_next()
        if not next_event:
            return

        from core.runtime.lifecycle import run_lifecycle_manager
        from core.protocol.shared_types import RunStatus
        
        run = run_lifecycle_manager.create_run(lane.session_id, next_event.event_id)
        run_id = run.run_id
        
        await lane.acquire_lock(run_id)
        run_lifecycle_manager.update_status(run_id, RunStatus.STARTED)
        slog.log_event("run_started", {"run_id": run_id, "event_id": next_event.event_id}, session_id=lane.session_id, run_id=run_id)
        
        try:
            if self._executor_callback:
                run_lifecycle_manager.update_status(run_id, RunStatus.EXECUTING)
                try:
                    await self._executor_callback(next_event)
                    run_lifecycle_manager.update_status(run_id, RunStatus.COMPLETED)
                    slog.log_event("run_completed", {"run_id": run_id}, session_id=lane.session_id, run_id=run_id)
                except Exception as e:
                    slog.log_event("run_failed", {"run_id": run_id, "error": str(e)}, level="error", session_id=lane.session_id, run_id=run_id)
                    from core.runtime.lifecycle import RunError
                    run_lifecycle_manager.update_status(
                        run_id, 
                        RunStatus.FAILED, 
                        error=RunError(code="execution_failed", message=str(e))
                    )
            else:
                slog.log_event("run_dropped", {"run_id": run_id, "reason": "no_executor"}, level="warning", session_id=lane.session_id, run_id=run_id)
                run_lifecycle_manager.update_status(
                    run_id, 
                    RunStatus.FAILED, 
                    error=RunError(code="no_executor", message="No executor callback configured")
                )
        finally:
            lane.release_lock(run_id)
            # Check for more events
            if lane.get_pending_events():
                asyncio.create_task(self._trigger_scheduler(lane))

# Global Singleton
session_manager = SessionManager()
