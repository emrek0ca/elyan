import asyncio
import uuid
import time
from typing import Any, Dict, List, Optional
from core.protocol.events import BaseEvent
from utils.logger import get_logger

logger = get_logger("session_lane")

class QueuePolicy:
    COLLECT = "collect"
    FOLLOWUP = "followup"
    INTERRUPT = "interrupt"
    STEER = "steer"
    BACKLOG_SUMMARIZE = "backlog-summarize"

class SessionLane:
    """
    Manages the serialization of runs for a specific session.
    Ensures that only one run happens at a time per session (no tool races).
    """
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._lock = asyncio.Lock()
        self._queue: List[BaseEvent] = []
        self._active_run_id: Optional[str] = None
        self._last_activity = time.time()
        
    @property
    def is_locked(self) -> bool:
        return self._lock.locked()
        
    def touch(self):
        self._last_activity = time.time()

    async def enqueue(self, event: BaseEvent, policy: str = QueuePolicy.FOLLOWUP):
        self.touch()
        if not self.is_locked:
            # If not locked, we can just process it immediately
            self._queue.append(event)
            return

        # If locked, apply queue policy
        if policy == QueuePolicy.INTERRUPT:
            logger.warning(f"[Session {self.session_id}] Interruption requested by event {event.event_id}")
            # In a full implementation, we'd signal the active run to abort
            self._queue.insert(0, event)
        elif policy == QueuePolicy.COLLECT:
            # Append without triggering a new run until explicitly told
            self._queue.append(event)
        elif policy == QueuePolicy.STEER:
            logger.info(f"[Session {self.session_id}] Steering active run with event {event.event_id}")
            # Inject into active run's context (handled by runtime)
            self._queue.append(event) 
        else:
            # Default: Followup (FIFO)
            self._queue.append(event)
            
        logger.debug(f"[Session {self.session_id}] Enqueued event {event.event_id} (Queue size: {len(self._queue)})")

    async def acquire_lock(self, run_id: str):
        await self._lock.acquire()
        self._active_run_id = run_id
        logger.debug(f"[Session {self.session_id}] Lane locked by run {run_id}")

    def release_lock(self, run_id: str):
        if self._active_run_id == run_id:
            self._active_run_id = None
            try:
                self._lock.release()
                logger.debug(f"[Session {self.session_id}] Lane released by run {run_id}")
            except RuntimeError:
                pass
        else:
            logger.warning(f"[Session {self.session_id}] Run {run_id} tried to release lock held by {self._active_run_id}")

    def pop_next(self) -> Optional[BaseEvent]:
        if self._queue:
            return self._queue.pop(0)
        return None

    def get_pending_events(self) -> List[BaseEvent]:
        return list(self._queue)
