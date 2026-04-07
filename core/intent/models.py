"""
Intent System Data Models

Core dataclasses for intent recognition, task decomposition, and multi-task orchestration.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Optional, Dict, List
from enum import Enum
from datetime import datetime


class IntentConfidence(Enum):
    """Confidence levels for intent recognition."""
    CERTAIN = 0.95  # User memory or exact match
    HIGH = 0.85  # Tier 1/2 with clear signal
    MEDIUM = 0.70  # Tier 2 with moderate signal
    LOW = 0.50  # Tier 3 ambiguous
    UNCERTAIN = 0.30  # Requires user clarification


@dataclass
class TaskDefinition:
    """Single task within a multi-task decomposition."""
    task_id: str
    action: str  # Tool name (must be in AVAILABLE_TOOLS)
    params: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    output_key: str = ""  # Variable name for chaining
    priority: int = 0  # 0=default, 1=high, -1=low
    estimated_duration_ms: int = 100

    def validate(self, available_tools: set) -> tuple[bool, Optional[str]]:
        """Validate task definition against available tools."""
        if self.action not in available_tools:
            return False, f"Tool '{self.action}' not available"
        if not isinstance(self.params, dict):
            return False, f"Params must be dict, got {type(self.params)}"
        return True, None


@dataclass
class DependencyGraph:
    """Represents task dependencies and execution order."""
    tasks: List[TaskDefinition]
    execution_order: List[str] = field(default_factory=list)  # Task IDs in order
    parallel_groups: List[List[str]] = field(default_factory=list)  # Groups that can run in parallel
    circular_dependencies: bool = False
    estimated_total_ms: int = 0

    def is_valid(self) -> bool:
        """Check if graph has no circular dependencies."""
        return not self.circular_dependencies

    def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        """Get task by ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None


@dataclass
class ConversationContext:
    """Tracks conversation history for contextual intent recognition."""
    user_id: str
    message_history: List[Dict[str, Any]] = field(default_factory=list)
    last_intent: Optional[str] = None
    last_action_time: Optional[datetime] = None
    active_task_id: Optional[str] = None
    session_vars: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, intent: Optional[str] = None) -> None:
        """Add message to history."""
        self.message_history.append({
            "role": role,
            "content": content,
            "intent": intent,
            "timestamp": datetime.now().isoformat()
        })
        # Keep last 50 messages
        if len(self.message_history) > 50:
            self.message_history = self.message_history[-50:]

    def get_context_summary(self) -> str:
        """Get recent conversation summary for LLM context."""
        if not self.message_history:
            return ""
        recent = self.message_history[-5:]
        lines = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)


@dataclass
class IntentCandidate:
    """Candidate intent with confidence and reasoning."""
    action: str  # Tool name or special: multi_task, chat, clarify
    confidence: float  # 0.0-1.0
    reasoning: str  # Why this action?
    params: Dict[str, Any] = field(default_factory=dict)
    tasks: List[TaskDefinition] = field(default_factory=list)  # For multi_task
    source_tier: str = ""  # "tier1", "tier2", "tier3", or "memory"
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_certain(self) -> bool:
        """Check if confidence meets threshold for direct execution."""
        return self.confidence >= IntentConfidence.HIGH.value


@dataclass
class IntentResult:
    """Final intent recognition result."""
    user_input: str
    user_id: str
    action: str  # Tool name or multi_task/chat/clarify
    confidence: float  # 0.0-1.0
    params: Dict[str, Any] = field(default_factory=dict)

    # Multi-task related
    is_multi_task: bool = False
    tasks: List[TaskDefinition] = field(default_factory=list)
    dependency_graph: Optional[DependencyGraph] = None

    # Metadata
    reasoning: str = ""
    source_tier: str = ""  # Which tier provided this result
    candidates: List[IntentCandidate] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_options: List[str] = field(default_factory=list)

    # Execution
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    # Context
    context: Optional[ConversationContext] = None

    # Feedback
    user_confirmed: bool = False
    actual_action: Optional[str] = None  # What user actually wanted
    feedback_received: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        def _serialize_item(item: Any) -> Dict[str, Any]:
            if isinstance(item, dict):
                return dict(item)
            if hasattr(item, "to_dict") and callable(item.to_dict):
                try:
                    data = item.to_dict()
                    if isinstance(data, dict):
                        return dict(data)
                except Exception:
                    pass
            if is_dataclass(item):
                try:
                    data = asdict(item)
                    if isinstance(data, dict):
                        return dict(data)
                except Exception:
                    pass
            payload: Dict[str, Any] = {"value": str(item)}
            if hasattr(item, "__dict__"):
                for key, value in vars(item).items():
                    if not str(key).startswith("_"):
                        payload[str(key)] = value
            return payload

        return {
            "user_input": self.user_input,
            "user_id": self.user_id,
            "action": self.action,
            "confidence": self.confidence,
            "params": self.params,
            "is_multi_task": self.is_multi_task,
            "tasks": [_serialize_item(task) for task in self.tasks],
            "tasks_count": len(self.tasks),
            "dependency_graph": asdict(self.dependency_graph) if self.dependency_graph else None,
            "reasoning": self.reasoning,
            "source_tier": self.source_tier,
            "candidates": [candidate.to_dict() if hasattr(candidate, "to_dict") else _serialize_item(candidate) for candidate in self.candidates],
            "requires_clarification": self.requires_clarification,
            "clarification_options": list(self.clarification_options),
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
        }

    def was_correct(self) -> bool:
        """Check if intent was correct (used for learning)."""
        if self.feedback_received:
            return self.actual_action == self.action
        return self.user_confirmed
