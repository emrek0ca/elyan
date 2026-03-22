import json
import pathlib
from typing import Any, Dict, List, Optional
from core.protocol.shared_types import RunStatus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("run_checkpoints")

class RunCheckpoint(BaseModel):
    run_id: str
    session_id: str
    last_completed_step: int
    steps_data: List[Dict[str, Any]]
    context_snapshot: Dict[str, Any]
    timestamp: float = Field(default_factory=time.time)

class CheckpointManager:
    """
    Handles persistence and restoration of run states.
    Allows resuming interrupted tasks from the last successful step.
    """
    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self.base_dir = base_dir or pathlib.Path.home() / ".elyan" / "checkpoints"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, checkpoint: RunCheckpoint):
        path = self.base_dir / f"{checkpoint.run_id}.json"
        path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        slog.log_event("checkpoint_saved", {"run_id": checkpoint.run_id, "step": checkpoint.last_completed_step})

    def load_checkpoint(self, run_id: str) -> Optional[RunCheckpoint]:
        path = self.base_dir / f"{run_id}.json"
        if not path.exists():
            return None
        
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RunCheckpoint(**data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint {run_id}: {e}")
            return None

    def delete_checkpoint(self, run_id: str):
        path = self.base_dir / f"{run_id}.json"
        path.unlink(missing_ok=True)
        slog.log_event("checkpoint_deleted", {"run_id": run_id})

# Global instance
checkpoint_manager = CheckpointManager()
