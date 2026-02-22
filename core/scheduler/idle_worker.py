"""
core/scheduler/idle_worker.py
─────────────────────────────────────────────────────────────────────────────
Idle Worker Agent.
Activates when the user is away. Proactively finds optimizations, organizes
the codebase, or fetches daily news without being prompted.
"""

import asyncio
import time
from utils.logger import get_logger

logger = get_logger("idle_worker")

class IdleWorker:
    def __init__(self, agent_instance, idle_threshold_minutes: int = 60):
        self.agent = agent_instance
        self.idle_threshold_minutes = idle_threshold_minutes
        self._last_interaction_ts = time.time()
        self._running = False
        
    def ping(self):
        """Called by the main gateway/API whenever the user interacts."""
        self._last_interaction_ts = time.time()
        
    async def start(self):
        if self._running: return
        self._running = True
        logger.info(f"💤 IdleWorker started. Threshold: {self.idle_threshold_minutes}min")
        
        self._bg_task = asyncio.create_task(self._monitor_loop())
        
    def stop(self):
        self._running = False
        if hasattr(self, "_bg_task"):
            self._bg_task.cancel()
        logger.info("🛑 IdleWorker stopped.")

    async def _monitor_loop(self):
        from core.multi_agent.orchestrator import AgentOrchestrator
        from core.multi_agent.neural_router import NeuralRouter
        
        while self._running:
            await asyncio.sleep(60) # Check every minute
            
            idle_minutes = (time.time() - self._last_interaction_ts) / 60.0
            if idle_minutes >= self.idle_threshold_minutes:
                logger.info("🥱 System seems idle. Waking up to do background chores...")
                
                # Pick a random chore
                chores = [
                    "Bütün log dosyalarındaki gereksiz kalıntıları tespit et ve bir özet çıkar.",
                    "HackerNews ve teknoloji sitelerinde bugünkü yapay zeka haberlerini derleyip text olarak kaydet.",
                    "_MUTATOR_RUN_"
                ]
                import random
                chore = random.choice(chores)
                
                if chore == "_MUTATOR_RUN_":
                    logger.info("🧬 IdleWorker triggering Auto-Refactoring Core Sweep...")
                    from core.mutator import CoreMutator
                    mutator = CoreMutator(self.agent)
                    await mutator.auto_refactor()
                else:
                    logger.info(f"Idle Task Selected: {chore}")
                    try:
                        router = NeuralRouter(self.agent)
                        template = await router.route_request(chore)
                        orchestrator = AgentOrchestrator(self.agent)
                        await orchestrator.manage_flow(template, chore)
                    except Exception as e:
                        logger.error(f"Idle chore failed: {e}")
                
                # Reset timer so we don't spam chores
                self.ping() 

idle_worker = None

def init_idle_worker(agent_instance) -> IdleWorker:
    global idle_worker
    if idle_worker is None:
        idle_worker = IdleWorker(agent_instance)
    return idle_worker
