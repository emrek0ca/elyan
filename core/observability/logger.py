import json
import time
from typing import Any, Dict, Optional
from utils.logger import get_logger
from core.feature_flags import get_feature_flag_registry
from core.observability.trace_context import get_trace_context

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
        run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ):
        trace_context = get_trace_context()
        registry = get_feature_flag_registry()
        enrich_trace = registry.is_enabled("structured_log_trace_enrichment", default=True)
        payload = {
            "timestamp": time.time(),
            "component": self.component,
            "event_type": event_type,
            "session_id": session_id or (trace_context.session_id if enrich_trace and trace_context else None),
            "run_id": run_id,
            "trace_id": trace_id or (trace_context.trace_id if enrich_trace and trace_context else None),
            "request_id": request_id or (trace_context.request_id if enrich_trace and trace_context else None),
            "workspace_id": workspace_id or (trace_context.workspace_id if enrich_trace and trace_context else None),
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
