"""
Automation Registry — Persist ve Yönetim katmanı
Zamanlanmış görevleri (Natural Language Cron) ve otomasyonları saklar.
"""

import os
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional
from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("automation_registry")

class AutomationRegistry:
    def __init__(self):
        self.db_path = HOME_DIR / ".elyan" / "automations.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.automations: Dict[str, Any] = self._load()
        
    def _load(self) -> Dict[str, Any]:
        if not self.db_path.exists():
            return {}
        try:
            with open(self.db_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Registry load error: {e}")
            return {}

    def _save(self):
        try:
            with open(self.db_path, "w") as f:
                json.dump(self.automations, f, indent=2)
        except Exception as e:
            logger.error(f"Registry save error: {e}")

    def register(self, task_id: str, definition: Dict[str, Any]):
        definition["created_at"] = time.time()
        definition["status"] = "active"
        self.automations[task_id] = definition
        self._save()
        logger.info(f"Registered automation: {task_id}")

    def unregister(self, task_id: str):
        if task_id in self.automations:
            del self.automations[task_id]
            self._save()
            logger.info(f"Unregistered automation: {task_id}")

    def get_active(self) -> List[Dict[str, Any]]:
        return [v for k, v in self.automations.items() if v.get("status") == "active"]

    def update_last_run(self, task_id: str):
        if task_id in self.automations:
            self.automations[task_id]["last_run"] = time.time()
            self._save()

    async def start_scheduler(self, agent):
        """Otomasyon döngüsünü başlat."""
        self._running = True
        asyncio.create_task(self._scheduler_loop(agent))
        logger.info("Automation scheduler started")

    async def _scheduler_loop(self, agent):
        while getattr(self, "_running", False):
            try:
                now = time.time()
                active = self.get_active()
                
                for task in active:
                    # Simple check: if not run today or first run
                    last = task.get("last_run", 0)
                    if now - last > 3600: # Every hour for demo/test
                        logger.info(f"Triggering automation: {task['id']} -> {task['task']}")
                        # Trigger workflow or simple command
                        from core.pipeline import PipelineContext, pipeline_runner
                        ctx = PipelineContext(
                            user_input=task["task"],
                            user_id=task.get("user_id", "system"),
                            channel=task.get("channel", "automation")
                        )
                        asyncio.create_task(pipeline_runner.run(ctx, agent))
                        self.update_last_run(task["id"])
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            await asyncio.sleep(60) # Check every minute

# Global Instance
automation_registry = AutomationRegistry()
