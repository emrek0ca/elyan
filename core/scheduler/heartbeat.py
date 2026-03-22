import asyncio
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("heartbeat")

class HeartbeatManager:
    """Ensures Elyan uakes up periodically to perform self-maintenance."""
    
    def __init__(self, agent):
        self.agent = agent
        self._is_running = False
        self._task = None

    async def start(self):
        if not elyan_config.get("heartbeat.enabled", True):
            return
            
        self._is_running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat manager started.")

    async def stop(self):
        self._is_running = False
        if self._task:
            self._task.cancel()
        logger.info("Heartbeat manager stopped.")

    async def _loop(self):
        interval = elyan_config.get("heartbeat.interval_minutes", 360) * 60
        
        while self._is_running:
            try:
                await asyncio.sleep(interval)
                logger.info("Heartbeat: Waking up for self-maintenance...")
                try:
                    from core.autopilot import get_autopilot

                    await get_autopilot().run_tick(agent=self.agent, reason="heartbeat")
                except Exception as autopilot_exc:
                    logger.warning(f"Heartbeat autopilot tick failed: {autopilot_exc}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
