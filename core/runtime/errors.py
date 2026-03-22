from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class ErrorCategory(str, Enum):
    SCHEMA_FAILURE = "schema_failure"
    SESSION_FAILURE = "session_failure"
    PLANNER_FAILURE = "planner_failure"
    POLICY_DENIAL = "policy_denial"
    CAPABILITY_FAILURE = "capability_failure"
    VERIFICATION_FAILURE = "verification_failure"
    TIMEOUT = "timeout"
    NODE_UNAVAILABLE = "node_unavailable"
    MEMORY_WRITE_FAILURE = "memory_write_failure"
    UNKNOWN = "unknown"

class ElyanRuntimeError(Exception):
    """Base exception for all v2 runtime errors."""
    def __init__(
        self, 
        message: str, 
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.details = details or {}
        self.retryable = retryable

class SchemaError(ElyanRuntimeError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCategory.SCHEMA_FAILURE, details, retryable=False)

class PolicyError(ElyanRuntimeError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCategory.POLICY_DENIAL, details, retryable=False)

class CapabilityError(ElyanRuntimeError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None, retryable: bool = True):
        super().__init__(message, ErrorCategory.CAPABILITY_FAILURE, details, retryable=retryable)

class NodeError(ElyanRuntimeError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCategory.NODE_UNAVAILABLE, details, retryable=True)

class VerificationError(ElyanRuntimeError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorCategory.VERIFICATION_FAILURE, details, retryable=True)
