"""
Advanced Workflow Engine with Conditionals
Complex workflow execution with if-then-else, loops, variables
"""

import asyncio
import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("workflow_engine")


class NodeType(Enum):
    """Workflow node types"""
    ACTION = "action"
    CONDITION = "condition"
    LOOP = "loop"
    PARALLEL = "parallel"
    VARIABLE = "variable"
    WAIT = "wait"


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowContext:
    """Execution context with variables"""
    variables: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    iteration_count: int = 0
    max_iterations: int = 100


@dataclass
class WorkflowNode:
    """Represents a workflow node"""
    node_id: str
    node_type: NodeType
    config: Dict[str, Any]
    next_nodes: List[str] = field(default_factory=list)
    error_handler: Optional[str] = None


@dataclass
class Workflow:
    """Complete workflow definition"""
    workflow_id: str
    name: str
    description: str
    nodes: Dict[str, WorkflowNode]
    start_node: str
    context: WorkflowContext = field(default_factory=WorkflowContext)
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


class WorkflowEngine:
    """
    Advanced Workflow Engine
    - If-then-else conditionals
    - Loops (for, while)
    - Variables and expressions
    - Parallel execution
    - Error handling
    - Workflow templates
    """

    def __init__(self):
        self.active_workflows: Dict[str, Workflow] = {}
        self.workflow_history: List[Workflow] = []
        self.templates: Dict[str, Dict[str, Any]] = {}

        # Load templates
        self._load_templates()

        logger.info("Workflow Engine initialized")

    def create_workflow(
        self,
        name: str,
        description: str,
        nodes: Optional[Dict[str, Any]] = None,
        start_node: str = "start"
    ) -> str:
        """Create a new workflow"""
        import uuid
        workflow_id = str(uuid.uuid4())[:8]

        # Convert dict nodes to WorkflowNode objects
        workflow_nodes = {}
        if nodes:
            for node_id, node_data in nodes.items():
                workflow_nodes[node_id] = WorkflowNode(
                    node_id=node_id,
                    node_type=NodeType(node_data.get("type", "action")),
                    config=node_data.get("config", {}),
                    next_nodes=node_data.get("next", []),
                    error_handler=node_data.get("error_handler")
                )

        workflow = Workflow(
            workflow_id=workflow_id,
            name=name,
            description=description,
            nodes=workflow_nodes,
            start_node=start_node
        )

        self.active_workflows[workflow_id] = workflow
        logger.info(f"Created workflow: {workflow_id} ({name})")

        return workflow_id

    def create_from_template(
        self,
        template_name: str,
        variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create workflow from template"""
        if template_name not in self.templates:
            raise ValueError(f"Template not found: {template_name}")

        template = deepcopy(self.templates[template_name])

        # Apply variables to template
        if variables:
            for var_name, var_value in variables.items():
                template["context"]["variables"][var_name] = var_value

        return self.create_workflow(
            name=template["name"],
            description=template["description"],
            nodes=template["nodes"],
            start_node=template.get("start_node", "start")
        )

    async def execute_workflow(
        self,
        workflow_id: str,
        executor=None
    ) -> Dict[str, Any]:
        """Execute a workflow"""
        if workflow_id not in self.active_workflows:
            return {"success": False, "error": "Workflow not found"}

        workflow = self.active_workflows[workflow_id]
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = time.time()

        try:
            # Start from start node
            current_node_id = workflow.start_node
            visited = set()

            while current_node_id:
                # Prevent infinite loops
                if workflow.context.iteration_count > workflow.context.max_iterations:
                    raise Exception("Max iterations exceeded")

                workflow.context.iteration_count += 1

                # Execute current node
                current_node_id = await self._execute_node(
                    workflow,
                    current_node_id,
                    executor
                )

            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = time.time()

            # Move to history
            self.workflow_history.append(workflow)
            del self.active_workflows[workflow_id]

            return {
                "success": True,
                "workflow_id": workflow_id,
                "duration": workflow.completed_at - workflow.started_at,
                "results": workflow.context.results
            }

        except Exception as e:
            logger.error(f"Workflow execution error: {e}")
            workflow.status = WorkflowStatus.FAILED
            workflow.error = str(e)
            workflow.completed_at = time.time()
            return {"success": False, "error": str(e)}

    async def _execute_node(
        self,
        workflow: Workflow,
        node_id: str,
        executor
    ) -> Optional[str]:
        """Execute a single node and return next node ID"""
        if node_id not in workflow.nodes:
            logger.warning(f"Node not found: {node_id}")
            return None

        node = workflow.nodes[node_id]
        logger.debug(f"Executing node: {node_id} ({node.node_type.value})")

        try:
            if node.node_type == NodeType.ACTION:
                return await self._execute_action(workflow, node, executor)

            elif node.node_type == NodeType.CONDITION:
                return await self._execute_condition(workflow, node)

            elif node.node_type == NodeType.LOOP:
                return await self._execute_loop(workflow, node, executor)

            elif node.node_type == NodeType.PARALLEL:
                return await self._execute_parallel(workflow, node, executor)

            elif node.node_type == NodeType.VARIABLE:
                return await self._execute_variable(workflow, node)

            elif node.node_type == NodeType.WAIT:
                return await self._execute_wait(workflow, node)

            else:
                logger.error(f"Unknown node type: {node.node_type}")
                return None

        except Exception as e:
            logger.error(f"Node execution error: {e}")

            # Check for error handler
            if node.error_handler:
                return node.error_handler
            else:
                raise

    async def _execute_action(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        executor
    ) -> Optional[str]:
        """Execute an action node"""
        action = node.config.get("action")
        params = node.config.get("params", {})

        # Resolve variables in params
        resolved_params = self._resolve_variables(params, workflow.context)

        # Execute action
        if executor:
            from tools import AVAILABLE_TOOLS
            tool = AVAILABLE_TOOLS.get(action)

            if tool:
                result = await executor.execute(tool, resolved_params)
                workflow.context.results[node.node_id] = result
            else:
                logger.warning(f"Tool not found: {action}")

        # Return next node
        return node.next_nodes[0] if node.next_nodes else None

    async def _execute_condition(
        self,
        workflow: Workflow,
        node: WorkflowNode
    ) -> Optional[str]:
        """Execute a condition node (if-then-else)"""
        condition = node.config.get("condition")
        then_node = node.config.get("then")
        else_node = node.config.get("else")

        # Evaluate condition
        try:
            # Simple expression evaluation
            result = self._evaluate_expression(condition, workflow.context)

            if result:
                return then_node
            else:
                return else_node

        except Exception as e:
            logger.error(f"Condition evaluation error: {e}")
            return else_node

    async def _execute_loop(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        executor
    ) -> Optional[str]:
        """Execute a loop node"""
        loop_type = node.config.get("type", "for")  # for, while
        loop_body = node.config.get("body")

        if loop_type == "for":
            # For loop over collection
            collection = node.config.get("collection")
            items = self._resolve_variables(collection, workflow.context)

            if isinstance(items, list):
                for item in items:
                    # Set loop variable
                    var_name = node.config.get("variable", "item")
                    workflow.context.variables[var_name] = item

                    # Execute loop body
                    await self._execute_node(workflow, loop_body, executor)

        elif loop_type == "while":
            # While loop
            condition = node.config.get("condition")
            max_iterations = node.config.get("max_iterations", 100)
            iteration = 0

            while iteration < max_iterations:
                if not self._evaluate_expression(condition, workflow.context):
                    break

                await self._execute_node(workflow, loop_body, executor)
                iteration += 1

        # Return next node after loop
        return node.next_nodes[0] if node.next_nodes else None

    async def _execute_parallel(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        executor
    ) -> Optional[str]:
        """Execute parallel branches"""
        branches = node.config.get("branches", [])

        # Execute all branches in parallel
        tasks = [
            self._execute_node(workflow, branch, executor)
            for branch in branches
        ]

        await asyncio.gather(*tasks)

        # Return next node
        return node.next_nodes[0] if node.next_nodes else None

    async def _execute_variable(
        self,
        workflow: Workflow,
        node: WorkflowNode
    ) -> Optional[str]:
        """Set a variable"""
        var_name = node.config.get("name")
        var_value = node.config.get("value")

        # Resolve value if it's an expression
        resolved_value = self._resolve_variables(var_value, workflow.context)

        workflow.context.variables[var_name] = resolved_value

        return node.next_nodes[0] if node.next_nodes else None

    async def _execute_wait(
        self,
        workflow: Workflow,
        node: WorkflowNode
    ) -> Optional[str]:
        """Wait for specified duration"""
        duration = node.config.get("duration", 1)  # seconds
        await asyncio.sleep(duration)

        return node.next_nodes[0] if node.next_nodes else None

    def _resolve_variables(
        self,
        value: Any,
        context: WorkflowContext
    ) -> Any:
        """Resolve variables in value"""
        if isinstance(value, str):
            # Check for variable reference: ${variable_name}
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                return context.variables.get(var_name, value)
            return value

        elif isinstance(value, dict):
            return {k: self._resolve_variables(v, context) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._resolve_variables(item, context) for item in value]

        else:
            return value

    def _evaluate_expression(
        self,
        expression: str,
        context: WorkflowContext
    ) -> bool:
        """Evaluate a boolean expression"""
        # Simple expression evaluation
        # Supports: variable comparisons, boolean logic

        # Resolve variables
        resolved = expression
        for var_name, var_value in context.variables.items():
            resolved = resolved.replace(f"${{{var_name}}}", str(var_value))

        try:
            # Safe evaluation (limited scope)
            return eval(resolved, {"__builtins__": {}}, {})
        except:
            logger.error(f"Expression evaluation failed: {expression}")
            return False

    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow status"""
        workflow = self.active_workflows.get(workflow_id)

        if not workflow:
            # Check history
            for w in self.workflow_history:
                if w.workflow_id == workflow_id:
                    workflow = w
                    break

        if not workflow:
            return None

        return {
            "workflow_id": workflow.workflow_id,
            "name": workflow.name,
            "status": workflow.status.value,
            "iteration_count": workflow.context.iteration_count,
            "variables": workflow.context.variables,
            "results": workflow.context.results,
            "duration": (workflow.completed_at - workflow.started_at) if workflow.completed_at and workflow.started_at else None,
            "error": workflow.error
        }

    def save_template(
        self,
        name: str,
        workflow_definition: Dict[str, Any]
    ):
        """Save a workflow as template"""
        self.templates[name] = workflow_definition

        # Persist to disk
        template_file = HOME_DIR / ".elyan" / "workflow_templates.json"
        template_file.parent.mkdir(parents=True, exist_ok=True)

        with open(template_file, "w") as f:
            json.dump(self.templates, f, indent=2)

        logger.info(f"Saved workflow template: {name}")

    def _load_templates(self):
        """Load workflow templates from disk"""
        try:
            template_file = HOME_DIR / ".elyan" / "workflow_templates.json"
            if template_file.exists():
                with open(template_file, "r") as f:
                    self.templates = json.load(f)
                logger.info(f"Loaded {len(self.templates)} workflow templates")
        except Exception as e:
            logger.error(f"Failed to load templates: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get workflow engine summary"""
        return {
            "active_workflows": len(self.active_workflows),
            "completed_workflows": len(self.workflow_history),
            "available_templates": len(self.templates),
            "node_types": [t.value for t in NodeType]
        }


# Global instance
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    """Get or create global workflow engine instance"""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine
