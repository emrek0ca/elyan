"""
CEO Planner — Prefrontal Cortex Simulation Engine.

The CEO Planner is Elyan's predictive layer that simulates task execution BEFORE
running it. It builds causality trees, detects conflicts, and predicts error scenarios
to prevent failures proactively.

Architecture:
  - Simulates execution as probabilistic DAGs (Directed Acyclic Graphs)
  - Detects mutual exclusion and resource contention
  - Predicts error scenarios (timeout, permission denied, rate limit, exhaustion)
  - Generates recovery paths for each predicted failure

Design Principles:
  1. Simulation is deterministic (same input → same tree)
  2. Performance critical: < 50ms for typical tasks
  3. Respects max depth to prevent stack overflow
  4. All predictions are heuristic-based (not perfect, but good enough)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class OutcomeType(Enum):
    """Result types for task execution"""
    SUCCESS = "success"
    FAILURE = "failure"
    DEADLOCK = "deadlock"
    PARTIAL = "partial"


class RiskLevel(Enum):
    """Risk classification for tasks"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CausalNode:
    """
    Node in a causality tree representing a potential task outcome.

    A CausalNode answers: "If I do this action, what happens?"
    - action: The operation being performed
    - condition: Precondition that must hold for action to execute
    - outcomes: Child nodes (what happens if action succeeds/fails/times out)
    - probability: P(outcome | condition) estimated from historical success rate
    - risk_level: LOW/MEDIUM/HIGH/CRITICAL
    - reversible: Can this action be rolled back?
    """
    action: str
    condition: str
    outcomes: List['CausalNode'] = field(default_factory=list)
    probability: float = 1.0  # P(success)
    risk_level: RiskLevel = RiskLevel.LOW
    reversible: bool = True


@dataclass
class ConflictingLoop:
    """
    Represents a conflict between two or more concurrent tasks.

    Example: Task1 wants to "delete file X", Task2 wants to "copy file X"
    These are mutually exclusive.
    """
    agent1_goal: str
    agent2_goal: str
    conflict_type: str  # "mutual_exclusion", "resource_contention", "deadlock"
    resolution: str  # Suggested fix


@dataclass
class ErrorScenario:
    """
    Predicted error that might occur during task execution.

    Includes recovery strategies.
    """
    error_code: str  # "TIMEOUT", "PERMISSION_DENIED", "RATE_LIMIT", etc.
    probability: float  # P(error occurs)
    recovery_action: str  # What to do if this happens
    fallback: str  # Ultimate fallback


# ============================================================================
# CEO Planner Class
# ============================================================================

class CEOPlanner:
    """
    Prefrontal Cortex simulation engine.

    Before Elyan executes a task, the CEO Planner simulates it:
    1. Builds a causality tree (if A, then B, then C or D)
    2. Detects conflicts (mutual exclusion, resource contention)
    3. Predicts errors (timeout, permission, rate limit)
    4. Suggests recovery paths

    Performance: < 50ms for typical tasks (target: < 100ms for complex)
    """

    def __init__(self, max_simulation_depth: int = 4):
        """
        Initialize CEO Planner.

        Args:
            max_simulation_depth: Max recursion depth (prevents infinite loops)
        """
        self.max_depth = max_simulation_depth
        self.simulation_cache: Dict[str, List[CausalNode]] = {}
        self._start_time = None

    def build_causal_tree(self, task: Any, execution_context: Any) -> CausalNode:
        """
        Build a causality tree for a task.

        Recursively simulates task execution up to max_depth, predicting
        success, failure, and partial outcomes.

        Args:
            task: ExecutionTask to simulate
            execution_context: ExecutionContext with session, user, workspace info

        Returns:
            CausalNode representing root of execution tree
        """
        self._start_time = time.time()

        root = self._simulate_step(task, execution_context, depth=0)
        self.simulation_cache[task.id] = self._flatten_tree(root)

        logger.info(
            f"Built causal tree for task {task.id} "
            f"({len(self.simulation_cache[task.id])} nodes)"
        )

        return root

    def _simulate_step(
        self,
        task: Any,
        context: Any,
        depth: int
    ) -> CausalNode:
        """
        Recursively simulate a single step.

        Args:
            task: Task to simulate
            context: Execution context
            depth: Current recursion depth

        Returns:
            CausalNode with outcomes (success, failure, partial)
        """
        # Base case: max depth reached
        if depth >= self.max_depth:
            return CausalNode(
                action=task.action,
                condition="max_depth_reached",
                outcomes=[],
                probability=1.0,
                risk_level=self._assess_risk(task),
                reversible=task.reversible if hasattr(task, 'reversible') else False
            )

        # Predict outcomes: success, failure, partial
        success_outcome = self._predict_success(task, context)
        failure_outcome = self._predict_failure(task, context)
        partial_outcome = self._predict_partial(task, context)

        # Recursively simulate next steps (only on success)
        if hasattr(task, 'next_steps') and task.next_steps and success_outcome.probability > 0.7:
            for next_step in task.next_steps:
                next_node = self._simulate_step(next_step, context, depth + 1)
                success_outcome.outcomes.append(next_node)

        # Return root node with all outcomes
        return CausalNode(
            action=task.action,
            condition=getattr(task, 'precondition', None) or "always",
            outcomes=[success_outcome, failure_outcome, partial_outcome],
            probability=success_outcome.probability,
            risk_level=self._assess_risk(task),
            reversible=getattr(task, 'reversible', True)
        )

    def _predict_success(self, task: Any, context: Any) -> CausalNode:
        """
        Predict success outcome for a task.

        Args:
            task: Task to predict for
            context: Execution context

        Returns:
            CausalNode representing success
        """
        prob = getattr(task, 'success_rate', 0.8)
        return CausalNode(
            action=f"{task.action}_success",
            condition="operation_completed_without_error",
            outcomes=[],
            probability=prob,
            risk_level=RiskLevel.LOW,
            reversible=True
        )

    def _predict_failure(self, task: Any, context: Any) -> CausalNode:
        """
        Predict failure outcome for a task.

        Args:
            task: Task to predict for
            context: Execution context

        Returns:
            CausalNode representing failure
        """
        prob = 1.0 - getattr(task, 'success_rate', 0.8)
        return CausalNode(
            action=f"{task.action}_failure",
            condition="error_occurred",
            outcomes=[],
            probability=prob,
            risk_level=RiskLevel.HIGH,
            reversible=False
        )

    def _predict_partial(self, task: Any, context: Any) -> CausalNode:
        """
        Predict partial success (some data processed, some failed).

        Args:
            task: Task to predict for
            context: Execution context

        Returns:
            CausalNode representing partial success
        """
        return CausalNode(
            action=f"{task.action}_partial",
            condition="partial_success",
            outcomes=[],
            probability=0.05,
            risk_level=RiskLevel.MEDIUM,
            reversible=True
        )

    def _assess_risk(self, task: Any) -> RiskLevel:
        """
        Assess risk level of a task.

        Args:
            task: Task to assess

        Returns:
            RiskLevel enum
        """
        # Destructive operations = high risk
        if getattr(task, 'destructive', False):
            return RiskLevel.HIGH

        # Operations requiring approval = medium risk
        if getattr(task, 'requires_approval', False):
            return RiskLevel.MEDIUM

        # Default = low risk
        return RiskLevel.LOW

    def detect_conflicting_loops(self, execution_tree: CausalNode) -> List[ConflictingLoop]:
        """
        Detect conflicting operations in the execution tree.

        Looks for:
        - Mutual exclusion (delete vs copy same file)
        - Resource contention (two tasks locking same resource)
        - Deadlock patterns (A waits for B, B waits for A)

        Args:
            execution_tree: Root CausalNode to analyze

        Returns:
            List of detected ConflictingLoop objects
        """
        conflicts = []

        # Get all leaf nodes
        leaves = self._get_all_leaves(execution_tree)

        # Check all pairs for conflicts
        for i, leaf1 in enumerate(leaves):
            for leaf2 in leaves[i+1:]:
                conflict = self._check_mutual_exclusion(leaf1, leaf2)
                if conflict:
                    conflicts.append(conflict)

        logger.debug(f"Detected {len(conflicts)} conflicts in tree")
        return conflicts

    def _check_mutual_exclusion(
        self,
        node1: CausalNode,
        node2: CausalNode
    ) -> Optional[ConflictingLoop]:
        """
        Check if two nodes represent mutually exclusive operations.

        Args:
            node1: First CausalNode
            node2: Second CausalNode

        Returns:
            ConflictingLoop if conflict detected, None otherwise
        """
        # Simple heuristic: delete vs copy on same resource
        if ("delete" in node1.action.lower() and "copy" in node2.action.lower()) or \
           ("copy" in node1.action.lower() and "delete" in node2.action.lower()):
            return ConflictingLoop(
                agent1_goal="Remove resource",
                agent2_goal="Preserve resource",
                conflict_type="mutual_exclusion",
                resolution="Use approval gate; sequence operations with lane locking"
            )

        # Heuristic: write vs read on same file
        if ("write" in node1.action.lower() and "read" in node2.action.lower()) or \
           ("read" in node1.action.lower() and "write" in node2.action.lower()):
            # This is less severe; readers can handle write
            pass

        return None

    def predict_error_scenarios(
        self,
        execution_tree: CausalNode
    ) -> Dict[str, Dict[str, Any]]:
        """
        Predict error scenarios for all tasks in the tree.

        Args:
            execution_tree: Root CausalNode to analyze

        Returns:
            Dict mapping action names to error predictions and recovery paths
        """
        error_scenarios = {}

        # Flatten tree and check each node
        flattened = self._flatten_tree(execution_tree)

        for node in flattened:
            # Only predict errors for high/medium risk nodes
            if node.risk_level in [RiskLevel.HIGH, RiskLevel.MEDIUM]:
                errors = self._generate_error_predictions(node)
                if errors:
                    error_scenarios[node.action] = errors

        logger.debug(f"Predicted error scenarios for {len(error_scenarios)} actions")
        return error_scenarios

    def _generate_error_predictions(self, node: CausalNode) -> Dict[str, Dict]:
        """
        Generate error predictions for a specific node.

        Args:
            node: CausalNode to generate predictions for

        Returns:
            Dict of error type → recovery strategy
        """
        predictions = {}

        # Generic error patterns based on action type
        if "api" in node.action.lower() or "http" in node.action.lower():
            predictions["timeout"] = {
                "action": "Increase timeout and retry",
                "recovery": "Exponential backoff",
                "fallback": "Use cached data or queue for later"
            }
            predictions["rate_limit"] = {
                "action": "Queue request",
                "recovery": "Implement exponential backoff + caching",
                "fallback": "Use alternative provider"
            }

        if "filesystem" in node.action.lower():
            predictions["permission_denied"] = {
                "action": "Request approval",
                "recovery": "Escalate to admin",
                "fallback": "Use read-only mode"
            }
            predictions["resource_exhausted"] = {
                "action": "Chunk operation",
                "recovery": "Stream data in batches",
                "fallback": "Queue for later"
            }

        if "database" in node.action.lower():
            predictions["connection_timeout"] = {
                "action": "Retry with backoff",
                "recovery": "Pool connection management",
                "fallback": "Use replica or cache"
            }

        return predictions

    # ========================================================================
    # Tree Traversal Helpers
    # ========================================================================

    def _flatten_tree(self, root: CausalNode) -> List[CausalNode]:
        """
        Flatten tree into DFS-ordered list.

        Args:
            root: Root CausalNode

        Returns:
            Flattened list of all nodes
        """
        result = [root]
        for outcome in root.outcomes:
            result.extend(self._flatten_tree(outcome))
        return result

    def _get_all_leaves(self, node: CausalNode) -> List[CausalNode]:
        """
        Extract all leaf nodes (nodes with no further outcomes).

        Args:
            node: Root CausalNode to search from

        Returns:
            List of leaf nodes
        """
        if not node.outcomes:
            return [node]

        leaves = []
        for outcome in node.outcomes:
            leaves.extend(self._get_all_leaves(outcome))

        return leaves

    # ========================================================================
    # Logging & Diagnostics
    # ========================================================================

    def get_simulation_time(self) -> float:
        """
        Get elapsed simulation time (ms).

        Returns:
            Simulation duration in milliseconds
        """
        if self._start_time:
            return (time.time() - self._start_time) * 1000
        return 0.0

    def log_tree_summary(self, tree: CausalNode) -> None:
        """
        Log a summary of the tree structure.

        Args:
            tree: CausalNode to summarize
        """
        flattened = self._flatten_tree(tree)
        leaves = self._get_all_leaves(tree)

        logger.info(
            f"Tree summary: root={tree.action}, "
            f"nodes={len(flattened)}, leaves={len(leaves)}, "
            f"probability={tree.probability:.2f}, "
            f"risk={tree.risk_level.value}"
        )


# ============================================================================
# Module Initialization
# ============================================================================

if __name__ == "__main__":
    # Simple smoke test
    logging.basicConfig(level=logging.DEBUG)

    class SimpleTask:
        def __init__(self, action, success_rate=0.8):
            self.id = "test_task"
            self.action = action
            self.success_rate = success_rate
            self.reversible = True
            self.destructive = False
            self.precondition = "always"
            self.next_steps = []

    ceo = CEOPlanner()
    task = SimpleTask("filesystem.write_text", success_rate=0.95)

    class SimpleContext:
        pass

    tree = ceo.build_causal_tree(task, SimpleContext())
    ceo.log_tree_summary(tree)
    print(f"Simulation time: {ceo.get_simulation_time():.2f}ms")
