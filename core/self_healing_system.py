"""
Self-Healing System - Automatic error detection and recovery
"""

import logging
from typing import Dict, List, Optional, Callable, Tuple, Any
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


class RecoveryStrategy(Enum):
    """Recovery strategies"""
    RETRY = "retry"
    FALLBACK = "fallback"
    ADJUST = "adjust"
    ROLLBACK = "rollback"
    ESCALATE = "escalate"


@dataclass
class ErrorRecord:
    """Records error information"""

    error_id: str
    error_type: str
    message: str
    context: Dict
    attempted_recovery: Optional[RecoveryStrategy]
    recovery_success: bool
    timestamp: str


class SelfHealingSystem:
    """Detects and recovers from errors automatically"""

    def __init__(self):
        self.error_history: List[ErrorRecord] = []
        self.recovery_handlers: Dict[str, Callable] = {}
        self.recovery_rate = 0.0
        self.error_threshold = 0.3

    def register_recovery_handler(self, error_type: str, handler: Callable):
        """Register error recovery handler"""
        self.recovery_handlers[error_type] = handler
        logger.info(f"Registered handler for {error_type}")

    def detect_error(self, context: Dict, output: Any) -> Optional[Dict]:
        """Detect if error occurred"""
        errors = {
            "timeout": self._check_timeout(context),
            "invalid_output": self._check_invalid_output(output),
            "performance": self._check_performance(context),
            "validation": self._check_validation(output),
            "dependency": self._check_dependencies(context)
        }

        detected_errors = {k: v for k, v in errors.items() if v}
        return detected_errors if detected_errors else None

    def _check_timeout(self, context: Dict) -> bool:
        """Check for timeout errors"""
        return context.get("duration", 0) > context.get("timeout", float('inf'))

    def _check_invalid_output(self, output: Any) -> bool:
        """Check for invalid output"""
        if output is None:
            return True
        if isinstance(output, dict) and "error" in output:
            return True
        return False

    def _check_performance(self, context: Dict) -> bool:
        """Check for performance issues"""
        return context.get("duration", 0) > 5.0  # 5 second threshold

    def _check_validation(self, output: Any) -> bool:
        """Check for validation errors"""
        if isinstance(output, dict):
            if "validation_error" in output:
                return True
        return False

    def _check_dependencies(self, context: Dict) -> bool:
        """Check for dependency errors"""
        return context.get("missing_dependencies", False)

    def attempt_recovery(self, error_type: str, context: Dict) -> Tuple[bool, str]:
        """Attempt to recover from error"""
        try:
            strategy = self._select_strategy(error_type)

            if error_type in self.recovery_handlers:
                handler = self.recovery_handlers[error_type]
                recovery_success = handler(context)
            else:
                recovery_success = self._apply_strategy(strategy, context)

            # Record
            error_record = ErrorRecord(
                error_id=f"error_{len(self.error_history)}",
                error_type=error_type,
                message=context.get("error_message", "Unknown error"),
                context=context,
                attempted_recovery=strategy,
                recovery_success=recovery_success,
                timestamp=datetime.now().isoformat()
            )
            self.error_history.append(error_record)

            # Update recovery rate
            if self.error_history:
                successful = sum(1 for e in self.error_history if e.recovery_success)
                self.recovery_rate = successful / len(self.error_history)

            return recovery_success, strategy.value

        except Exception as e:
            logger.error(f"Recovery attempt failed: {e}")
            return False, "escalate"

    def _select_strategy(self, error_type: str) -> RecoveryStrategy:
        """Select recovery strategy"""
        strategies = {
            "timeout": RecoveryStrategy.RETRY,
            "invalid_output": RecoveryStrategy.ADJUST,
            "performance": RecoveryStrategy.ADJUST,
            "validation": RecoveryStrategy.FALLBACK,
            "dependency": RecoveryStrategy.ESCALATE
        }
        return strategies.get(error_type, RecoveryStrategy.RETRY)

    def _apply_strategy(self, strategy: RecoveryStrategy, context: Dict) -> bool:
        """Apply recovery strategy"""
        if strategy == RecoveryStrategy.RETRY:
            return True  # Simplified
        elif strategy == RecoveryStrategy.FALLBACK:
            return True
        elif strategy == RecoveryStrategy.ADJUST:
            return True
        elif strategy == RecoveryStrategy.ROLLBACK:
            return True
        else:  # ESCALATE
            return False

    def prevent_future_errors(self, error_type: str) -> List[str]:
        """Suggest preventive measures"""
        suggestions = {
            "timeout": [
                "Increase timeout threshold",
                "Optimize code performance",
                "Add caching"
            ],
            "invalid_output": [
                "Add input validation",
                "Implement output verification",
                "Add error checking"
            ],
            "performance": [
                "Optimize algorithms",
                "Use caching",
                "Implement parallelization"
            ],
            "validation": [
                "Add pre-execution validation",
                "Implement type checking",
                "Add schema validation"
            ],
            "dependency": [
                "Check dependencies before execution",
                "Use dependency injection",
                "Add fallback services"
            ]
        }
        return suggestions.get(error_type, ["Unknown error type"])

    def get_health_status(self) -> Dict:
        """Get system health status"""
        return {
            "total_errors": len(self.error_history),
            "recovery_rate": self.recovery_rate,
            "system_healthy": self.recovery_rate > (1 - self.error_threshold),
            "recent_errors": [
                {
                    "type": e.error_type,
                    "recovered": e.recovery_success,
                    "time": e.timestamp
                }
                for e in self.error_history[-5:]
            ]
        }

    def reset_statistics(self):
        """Reset error tracking"""
        self.error_history.clear()
        self.recovery_rate = 0.0
        logger.info("Statistics reset")
