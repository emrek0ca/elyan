import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.observability.logger import get_structured_logger

slog = get_structured_logger("run_scheduler")

class ScheduledMission(BaseModel):
    mission_id: str = Field(default_factory=lambda: f"miss_{uuid.uuid4().hex[:8]}")
    goal: str
    schedule_type: str # once, interval, cron
    trigger_value: Any # timestamp, seconds, or cron string
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MissionScheduler:
    """
    Manages missions that are scheduled for future or periodic execution.
    """
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self._missions: Dict[str, ScheduledMission] = {}
        self._running = False

    def schedule_mission(self, mission: ScheduledMission):
        self._missions[mission.mission_id] = mission
        slog.log_event("mission_scheduled", mission.model_dump())

    async def start(self):
        self._running = True
        asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False

    async def _loop(self):
        while self._running:
            now = time.time()
            for mission in list(self._missions.values()):
                if not mission.enabled:
                    continue
                
                if mission.next_run and now >= mission.next_run:
                    slog.log_event("mission_triggered", {"mission_id": mission.mission_id, "goal": mission.goal})
                    
                    # Create a new run for this mission
                    # session_id could be 'scheduled' or a specific user session
                    session_id = mission.metadata.get("session_id", "sess_scheduled")
                    
                    from core.runtime.lifecycle import run_lifecycle_manager
                    run = run_lifecycle_manager.create_run(session_id)
                    
                    asyncio.create_task(self.orchestrator.execute_run(session_id, run.run_id, mission.goal))
                    
                    mission.last_run = now
                    # Update next_run if periodic
                    if mission.schedule_type == "interval":
                        mission.next_run = now + mission.trigger_value
                    else:
                        mission.next_run = None # For 'once'
            
            await asyncio.sleep(10) # Tick every 10 seconds

# Note: This will be instantiated by the GatewayServer
