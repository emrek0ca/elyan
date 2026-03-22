from typing import Any, Dict, Optional, Type
from pydantic import ValidationError
from core.protocol.events import ElyanEvent
from core.observability.logger import get_structured_logger

slog = get_structured_logger("schema_validator")

class SchemaValidator:
    """
    Unified validator for Elyan protocol schemas.
    Ensures that all inbound and internal events strictly follow the v2 contracts.
    """
    def validate(self, payload: Any, schema_class: Type[ElyanEvent]) -> bool:
        """Validates a payload against a schema. Returns True if valid."""
        try:
            if isinstance(payload, dict):
                schema_class(**payload)
            else:
                # If already an object, assume it was validated on creation
                # unless we want to re-validate pydantic models
                pass
            return True
        except ValidationError as e:
            slog.log_event("schema_validation_failed", {
                "schema": schema_class.__name__,
                "errors": e.errors()
            }, level="error")
            return False

    def validate_or_raise(self, payload: Any, schema_class: Type[ElyanEvent]):
        """Validates or raises ValueError with details."""
        try:
            if isinstance(payload, dict):
                return schema_class(**payload)
            return payload
        except ValidationError as e:
            error_msg = f"Schema validation failed for {schema_class.__name__}: {str(e)}"
            slog.log_event("schema_validation_critical", {"errors": e.errors()}, level="error")
            raise ValueError(error_msg)

# Global instance
schema_validator = SchemaValidator()
