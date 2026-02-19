import time
import json
from typing import Optional, Dict, Any
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("action_lock")

class ActionLockManager:
    """Manages 'Production Mode' to keep Elyan focused on delivery tasks."""
    
    def __init__(self):
        self.is_locked = False
        self.current_task_id: Optional[str] = None
        self.locked_at: Optional[float] = None
        self.progress: float = 0.0
        self.status_message: str = ""

    def lock(self, task_id: str, message: str = "Başlatıldı"):
        self.is_locked = True
        self.current_task_id = task_id
        self.locked_at = time.time()
        self.status_message = message
        self.progress = 0.0
        logger.info(f"Action-Lock ENABLED for task: {task_id}")

    def unlock(self):
        logger.info(f"Action-Lock DISABLED (Completed task: {self.current_task_id})")
        self.is_locked = False
        self.current_task_id = None
        self.locked_at = None
        self.progress = 0.0

    def update_status(self, progress: float, message: str):
        self.progress = progress
        self.status_message = message

    def get_status_prefix(self) -> str:
        if self.is_locked:
            pct = int(self.progress * 100)
            return f"[URETIM %{pct}] "
        return ""

# Global instance
action_lock = ActionLockManager()
