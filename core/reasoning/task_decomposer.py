"""
core/reasoning/task_decomposer.py
─────────────────────────────────────────────────────────────────────────────
Task Decomposer (Phase 30).
Breaks complex user requests into a dependency-ordered graph of subtasks.
Prevents Elyan from attempting to do everything in a single chaotic LLM call.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Dict
from utils.logger import get_logger

logger = get_logger("decomposer")

@dataclass
class SubTask:
    id: int
    description: str
    tool: str = "general"
    depends_on: List[int] = field(default_factory=list)
    status: str = "pending"  # pending, running, done, failed
    result: str = ""

@dataclass
class TaskGraph:
    original_request: str
    subtasks: List[SubTask] = field(default_factory=list)
    complexity: str = "medium"

class TaskDecomposer:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        
    async def decompose(self, request: str) -> TaskGraph:
        """Uses the LLM to break a complex request into ordered subtasks."""
        logger.info(f"📋 Decomposing: {request[:80]}...")
        
        prompt = f"""
SEN BİR GÖREV MİMARI'SIN. Kullanıcının aşağıdaki isteğini 3-8 arası alt göreve ayır.
Her alt görev bağımsız olarak çalıştırılabilmeli. Bağımlılıkları belirt.

İstek: {request}

MUTLAKA geçerli JSON döndür. Başka bir şey yazma:
{{
  "complexity": "low|medium|high",
  "subtasks": [
    {{"id": 1, "description": "Alt görev açıklaması", "tool": "araç adı", "depends_on": []}},
    {{"id": 2, "description": "İkinci görev", "tool": "araç", "depends_on": [1]}}
  ]
}}
"""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        raw = await orch._run_specialist("executor", prompt)
        
        return self._parse_graph(request, raw)
    
    def _parse_graph(self, request: str, raw_response: str) -> TaskGraph:
        """Safely parse the LLM's JSON response into a TaskGraph."""
        graph = TaskGraph(original_request=request)
        
        try:
            match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if match:
                data = json.loads(match.group())
                graph.complexity = data.get("complexity", "medium")
                
                for st in data.get("subtasks", []):
                    graph.subtasks.append(SubTask(
                        id=st.get("id", 0),
                        description=st.get("description", ""),
                        tool=st.get("tool", "general"),
                        depends_on=st.get("depends_on", [])
                    ))
                    
            logger.info(f"📋 Decomposed into {len(graph.subtasks)} subtasks (complexity: {graph.complexity})")
        except Exception as e:
            logger.error(f"Decomposition parse error: {e}")
            graph.subtasks.append(SubTask(id=1, description=request, tool="general"))
            
        return graph
    
    async def execute_graph(self, graph: TaskGraph) -> Dict:
        """Execute subtasks in dependency order."""
        results = {}
        
        for subtask in self._topological_sort(graph.subtasks):
            # Wait for dependencies
            deps_met = all(
                results.get(dep_id, {}).get("status") == "done" 
                for dep_id in subtask.depends_on
            )
            
            if not deps_met:
                subtask.status = "failed"
                results[subtask.id] = {"status": "failed", "error": "Dependency not met"}
                continue
            
            subtask.status = "running"
            logger.info(f"  ▶ SubTask {subtask.id}: {subtask.description[:60]}...")
            
            try:
                from core.multi_agent.orchestrator import AgentOrchestrator
                orch = AgentOrchestrator(self.agent)
                
                dep_context = "\n".join(
                    f"Önceki adım {d}: {results.get(d, {}).get('result', '')[:200]}" 
                    for d in subtask.depends_on
                )
                
                full_prompt = f"Alt görev: {subtask.description}\nÖnceki sonuçlar: {dep_context}"
                subtask.result = await orch._run_specialist("executor", full_prompt)
                subtask.status = "done"
                results[subtask.id] = {"status": "done", "result": subtask.result}
                
            except Exception as e:
                subtask.status = "failed"
                results[subtask.id] = {"status": "failed", "error": str(e)}
        
        return results
    
    def _topological_sort(self, subtasks: List[SubTask]) -> List[SubTask]:
        """Sort subtasks by dependency order."""
        visited = set()
        order = []
        task_map = {st.id: st for st in subtasks}
        
        def visit(task_id):
            if task_id in visited:
                return
            visited.add(task_id)
            task = task_map.get(task_id)
            if task:
                for dep in task.depends_on:
                    visit(dep)
                order.append(task)
        
        for st in subtasks:
            visit(st.id)
        
        return order
