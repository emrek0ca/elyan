"""
core/task_engine/_state.py
TaskResult ve TaskDefinition dataclass'ları — Sprint K modüler bölünme.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class TaskResult:
    """Structured task result"""
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class TaskDefinition:
    """Single task definition"""
    id: str
    action: str
    params: Dict[str, Any]
    description: str
    dependencies: List[str] = field(default_factory=list)
    is_risky: bool = False
    requires_approval: bool = False
