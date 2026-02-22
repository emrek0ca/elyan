"""
core/ux/progress_tracker.py
─────────────────────────────────────────────────────────────────────────────
Real-Time Progress Tracker (Phase 33).
Provides structured progress updates for multi-step tasks so the user 
never sits in silence wondering what's happening.
"""

import time
from typing import Callable, Optional
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("progress")

@dataclass
class ProgressState:
    task_name: str
    total_steps: int
    current_step: int = 0
    current_description: str = ""
    started_at: float = field(default_factory=time.time)
    percent: float = 0.0
    status: str = "running"  # running, paused, done, error

class ProgressTracker:
    def __init__(self, task_name: str, total_steps: int, on_update: Optional[Callable] = None):
        self.state = ProgressState(task_name=task_name, total_steps=total_steps)
        self.on_update = on_update  # Callback for real-time UI/Telegram updates
        self._history = []
    
    def advance(self, description: str):
        """Advance to the next step and notify."""
        self.state.current_step += 1
        self.state.current_description = description
        self.state.percent = (self.state.current_step / max(self.state.total_steps, 1)) * 100
        
        elapsed = time.time() - self.state.started_at
        
        self._history.append({
            "step": self.state.current_step,
            "description": description,
            "elapsed": elapsed
        })
        
        bar = self._render_bar()
        logger.info(f"📊 {bar} {description}")
        
        if self.on_update:
            self.on_update(self.state)
    
    def complete(self, summary: str = ""):
        """Mark the task as done."""
        self.state.status = "done"
        self.state.percent = 100.0
        elapsed = time.time() - self.state.started_at
        logger.info(f"✅ {self.state.task_name} tamamlandı ({elapsed:.1f}s). {summary}")
        
        if self.on_update:
            self.on_update(self.state)
    
    def error(self, message: str):
        """Mark the task as errored."""
        self.state.status = "error"
        logger.error(f"❌ {self.state.task_name} hatası: {message}")
    
    def _render_bar(self) -> str:
        """Render a visual progress bar."""
        filled = int(self.state.percent / 5)
        empty = 20 - filled
        bar = "█" * filled + "░" * empty
        return f"[{bar}] {self.state.percent:.0f}%"
    
    def get_eta_seconds(self) -> float:
        """Estimate remaining time based on average step duration."""
        if self.state.current_step == 0:
            return 0
        elapsed = time.time() - self.state.started_at
        avg_per_step = elapsed / self.state.current_step
        remaining = self.state.total_steps - self.state.current_step
        return avg_per_step * remaining
