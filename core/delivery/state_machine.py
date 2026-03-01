from enum import Enum
from typing import Dict, Any, List, Optional
import time
from utils.logger import get_logger

logger = get_logger("delivery_state_machine")

class DeliveryState(Enum):
    IDLE = "idle"
    INTAKE = "intake"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    DELIVERED = "delivered"
    FAILED = "failed"

class DeliveryProject:
    def __init__(self, project_id: str, name: str):
        self.project_id = project_id
        self.name = name
        self.state = DeliveryState.IDLE
        self.history: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}
        self.progress = 0
        self.started_at = time.time()
        self.updated_at = time.time()

    def transition_to(self, new_state: DeliveryState, metadata: Optional[Dict] = None):
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        
        entry = {
            "from": old_state.value,
            "to": new_state.value,
            "timestamp": self.updated_at,
            "metadata": metadata or {}
        }
        self.history.append(entry)
        
        # Automatic progress updates
        state_progress = {
            DeliveryState.IDLE: 0,
            DeliveryState.INTAKE: 10,
            DeliveryState.PLANNING: 30,
            DeliveryState.EXECUTING: 60,
            DeliveryState.VERIFYING: 90,
            DeliveryState.DELIVERED: 100,
            DeliveryState.FAILED: 0
        }
        self.progress = state_progress.get(new_state, self.progress)
        
        logger.info(f"Project '{self.name}' transition: {old_state.value} -> {new_state.value} ({self.progress}%)")

class DeliveryStateMachine:
    def __init__(self):
        self.projects: Dict[str, DeliveryProject] = {}

    def start_project(self, name: str) -> DeliveryProject:
        project_id = f"proj_{int(time.time())}"
        project = DeliveryProject(project_id, name)
        project.transition_to(DeliveryState.INTAKE)
        self.projects[project_id] = project
        return project

    def get_project(self, project_id: str) -> Optional[DeliveryProject]:
        return self.projects.get(project_id)

# Global instance
delivery_state_manager = DeliveryStateMachine()
