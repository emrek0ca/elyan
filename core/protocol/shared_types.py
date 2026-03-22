from enum import Enum

class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    WRITE_SAFE = "write_safe"
    WRITE_SENSITIVE = "write_sensitive"
    DESTRUCTIVE = "destructive"
    SYSTEM_CRITICAL = "system_critical"

class ExecutionMode(str, Enum):
    DIRECT = "direct"
    INSPECT = "inspect"
    TOOL_CALL = "tool_call"
    APPROVAL_GATE = "approval_gate"
    DELEGATED = "delegated"
    SCHEDULED = "scheduled"

class RunStatus(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class QueuePolicy(str, Enum):
    FOLLOWUP = "followup"
    INTERRUPT = "interrupt"
    MERGE = "merge"
    BACKLOG = "backlog"
    SUMMARIZE = "summarize"

class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    INCONCLUSIVE = "inconclusive"

class MemoryType(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    PROFILE = "profile"
    PROJECT = "project"

class NodeType(str, Enum):
    DESKTOP = "desktop"
    VPS = "vps"
    MOBILE = "mobile"
    BROWSER = "browser"

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"
