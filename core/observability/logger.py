import json
import time
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("observability")

class StructuredLogger:
    """
    Handles structured logging for the Elyan runtime.
    Produces logs that are easy to parse and analyze.
    """
    def __init__(self, component: str):
        self.component = component
        self._logger = get_logger(component)

    def log_event(
        self, 
        event_type: str, 
        data: Dict[str, Any], 
        level: str = "info",
        session_id: Optional[str] = None,
        run_id: Optional[str] = None
    ):
        payload = {
            "timestamp": time.time(),
            "component": self.component,
            "event_type": event_type,
            "session_id": session_id,
            "run_id": run_id,
            "data": data
        }
        
        message = json.dumps(payload, ensure_ascii=False)
        
        if level == "error":
            self._logger.error(message)
        elif level == "warning":
            self._logger.warning(message)
        elif level == "debug":
            self._logger.debug(message)
        else:
            self._logger.info(message)

def get_structured_logger(component: str) -> StructuredLogger:
    return StructuredLogger(component)
