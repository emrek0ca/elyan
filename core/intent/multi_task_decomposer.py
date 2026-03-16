"""
Multi-Task Decomposer

Decomposes multi-task intents into executable subtasks.
Contract-first: only uses existing tools.
Creates dependency graphs.
"""

import json
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from .models import TaskDefinition, DependencyGraph

logger = get_logger("multi_task_decomposer")

DECOMPOSITION_PROMPT = """
GÖREV: {task_description}

SADECE ŞU ARAÇLARI KULLANABİLİRSİN:
{available_tools}

KURALLAR:
1. Yeni tool icat ETME - sadece yukarıdakileri kullan
2. Parametreler SCHEMA'ya MUTLAKA UY
3. depends_on sadece önceki task_id'leri referans etsin
4. Paralel çalışabilecek görevler depends_on:[] olsun
5. Her görev TAM ve İSTIFADE EDİLEBİLİR olmalı

ÇIKTI (JSON):
{{
  "tasks": [
    {{
      "task_id": "t1",
      "action": "tool_name",
      "params": {{"key": "value"}},
      "depends_on": [],
      "output_key": "result_t1"
    }},
    {{
      "task_id": "t2",
      "action": "tool_name",
      "params": {{"input": "${{result_t1}}"}}
    }}
  ],
  "total_tasks": 2,
  "estimated_duration_ms": 5000
}}

Sadece JSON döndür, başka metin yok.
"""


class MultiTaskDecomposer:
    """Decompose multi-task intents into executable subtasks."""

    def __init__(self, llm_orchestrator=None):
        self.llm = llm_orchestrator

    def decompose(
        self,
        task_description: str,
        available_tools: Dict[str, Any]
    ) -> Optional[DependencyGraph]:
        """
        Decompose task into subtasks.

        Args:
            task_description: What user wants to do
            available_tools: Available tools dict

        Returns:
            DependencyGraph with executable tasks
        """
        try:
            # Build tool schema
            tool_schema = self._format_tool_schema(available_tools)

            # Build prompt
            prompt = DECOMPOSITION_PROMPT.format(
                task_description=task_description,
                available_tools=tool_schema
            )

            # Call LLM
            response = self._call_llm(prompt)
            if not response:
                logger.warning("Decomposer LLM returned empty response")
                return None

            # Parse response
            graph = self._parse_decomposition(response, available_tools)
            if graph:
                logger.info(f"Decomposed into {len(graph.tasks)} tasks")
            return graph

        except Exception as e:
            logger.error(f"Decomposition error: {e}")
            return None

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM for decomposition."""
        if not self.llm:
            logger.warning("Decomposer: LLM orchestrator not available")
            return None

        try:
            # Use fast provider for decomposition
            response = self.llm.call_groq(
                prompt=prompt,
                temperature=0.3,
                max_tokens=1500,
                timeout_ms=2000
            )
            if response:
                return response

            # Fallback
            response = self.llm.call_gemini(
                prompt=prompt,
                temperature=0.3,
                max_tokens=1500,
                timeout_ms=2000
            )
            return response

        except Exception as e:
            logger.error(f"Decomposer LLM call failed: {e}")
            return None

    def _format_tool_schema(self, available_tools: Dict[str, Any]) -> str:
        """Format tool schemas for prompt."""
        lines = []
        for tool_name, schema in available_tools.items():
            if isinstance(schema, dict):
                desc = schema.get("description", "")
                params = schema.get("params", {})
                lines.append(f"- {tool_name}: {desc}")
                if params:
                    for param_name, param_schema in params.items():
                        param_type = param_schema.get("type", "string") if isinstance(param_schema, dict) else "string"
                        param_desc = param_schema.get("description", "") if isinstance(param_schema, dict) else ""
                        lines.append(f"  - {param_name} ({param_type}): {param_desc}")
        return "\n".join(lines) if lines else "(No tools available)"

    def _parse_decomposition(self, response: str, available_tools: Dict[str, Any]) -> Optional[DependencyGraph]:
        """Parse decomposition response."""
        try:
            data = json.loads(response.strip())

            tasks_data = data.get("tasks", [])
            if not tasks_data:
                logger.warning("No tasks in decomposition")
                return None

            # Parse tasks
            tasks: List[TaskDefinition] = []
            for t in tasks_data:
                try:
                    task = TaskDefinition(
                        task_id=t.get("task_id", f"t{len(tasks)}"),
                        action=t.get("action", ""),
                        params=t.get("params", {}),
                        depends_on=t.get("depends_on", []),
                        output_key=t.get("output_key", "")
                    )

                    # Validate action
                    if task.action not in available_tools:
                        logger.warning(f"Task action '{task.action}' not in available tools")
                        continue

                    # Validate params schema
                    valid, error = task.validate(set(available_tools.keys()))
                    if not valid:
                        logger.warning(f"Task validation failed: {error}")
                        continue

                    tasks.append(task)

                except Exception as te:
                    logger.warning(f"Failed to parse task: {te}")
                    continue

            if not tasks:
                return None

            # Build execution order and detect cycles
            execution_order, parallel_groups = self._topological_sort(tasks)
            has_cycle = execution_order is None

            if has_cycle:
                logger.warning("Circular dependency detected in task graph")
                execution_order = [t.task_id for t in tasks]  # Fallback
                parallel_groups = [[t.task_id] for t in tasks]

            # Estimate total duration
            total_duration = sum(t.estimated_duration_ms for t in tasks)

            graph = DependencyGraph(
                tasks=tasks,
                execution_order=execution_order or [],
                parallel_groups=parallel_groups or [],
                circular_dependencies=has_cycle,
                estimated_total_ms=total_duration
            )

            return graph

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None

    def _topological_sort(self, tasks: List[TaskDefinition]) -> tuple[Optional[List[str]], List[List[str]]]:
        """
        Topological sort with cycle detection.

        Returns:
            (execution_order, parallel_groups) or (None, []) if cycle detected
        """
        task_map = {t.task_id: t for t in tasks}
        visited = set()
        rec_stack = set()
        order = []
        parallel_groups = []

        def visit(task_id: str, depth: int = 0) -> bool:
            if task_id in rec_stack:
                return False  # Cycle detected
            if task_id in visited:
                return True

            rec_stack.add(task_id)
            task = task_map.get(task_id)
            if not task:
                return True

            # Visit dependencies first
            for dep_id in task.depends_on:
                if not visit(dep_id, depth + 1):
                    return False

            rec_stack.remove(task_id)
            visited.add(task_id)
            order.append(task_id)
            return True

        # Visit all tasks
        for task in tasks:
            if task.task_id not in visited:
                if not visit(task.task_id):
                    return None, []  # Cycle detected

        # Group by dependency level
        for i, task_id in enumerate(order):
            task = task_map[task_id]
            if not task.depends_on:
                if not parallel_groups or parallel_groups[-1][0] in [
                    t.task_id for dep_list in parallel_groups for t in
                    [task_map.get(tid) for tid in dep_list] if t
                ]:
                    parallel_groups.append([task_id])
                else:
                    if len(parallel_groups) > 0:
                        parallel_groups[-1].append(task_id)
                    else:
                        parallel_groups.append([task_id])
            else:
                if parallel_groups:
                    parallel_groups[-1].append(task_id)
                else:
                    parallel_groups.append([task_id])

        return order, parallel_groups

    def validate_graph(self, graph: DependencyGraph, available_tools: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate dependency graph."""
        if graph.circular_dependencies:
            return False, "Circular dependencies detected"

        for task in graph.tasks:
            # Check action exists
            if task.action not in available_tools:
                return False, f"Action '{task.action}' not in available tools"

            # Check dependencies exist
            for dep_id in task.depends_on:
                if not graph.get_task(dep_id):
                    return False, f"Dependency '{dep_id}' not found"

        return True, None
