"""
core/multi_agent/neural_router.py
─────────────────────────────────────────────────────────────────────────────
Neural Router for transforming free-form requests into structured Job Templates.
Handles Tool Permissions, Complexity Classification, and Capability Budgeting.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
from utils.logger import get_logger

logger = get_logger("neural_router")

@dataclass
class ToolPermissionMatrix:
    allowed_tools: List[str]
    blocked_tools: List[str]
    requires_approval: List[str]
    max_network_calls: int = 10
    allowed_fs_paths: List[str] = field(default_factory=lambda: ["/Users/emrekoca/Desktop", "/tmp"])
    
    def can_execute(self, tool_name: str) -> bool:
        if tool_name in self.blocked_tools: 
            return False
        if "*" in self.allowed_tools or tool_name in self.allowed_tools: 
            return True
        return False
        
    def needs_approval(self, tool_name: str) -> bool:
        return tool_name in self.requires_approval

@dataclass
class JobTemplate:
    id: str
    name: str
    complexity_class: str # "Trivial", "Standard", "Complex", "Epic"
    required_capabilities: List[str]
    permissions: ToolPermissionMatrix
    expected_deliverables: List[str]
    max_tokens: int = 150000
    max_usd: float = 0.5
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "complexity_class": self.complexity_class,
            "required_capabilities": self.required_capabilities,
            "expected_deliverables": self.expected_deliverables
        }

# Predefined templates matching Elyan's common tasks
TEMPLATES = {
    "web_project_scaffold": JobTemplate(
        id="web_project_scaffold",
        name="Web Project Scaffolding",
        complexity_class="Standard",
        required_capabilities=["filesystem", "code_generation", "web_design"],
        permissions=ToolPermissionMatrix(
            allowed_tools=["write_file", "create_folder", "apply_patch"],
            blocked_tools=["run_command"],
            requires_approval=["shell_exec"]
        ),
        expected_deliverables=["index.html", "style.css", "app.js"],
        max_tokens=200000,
        max_usd=0.8
    ),
    "research_report": JobTemplate(
        id="research_report",
        name="Deep Research Report",
        complexity_class="Complex",
        required_capabilities=["web_search", "document_generation", "summarization"],
        permissions=ToolPermissionMatrix(
            allowed_tools=["web_search", "read_url", "write_word", "summarize_text"],
            blocked_tools=["write_file", "create_folder", "apply_patch"],
            requires_approval=[]
        ),
        expected_deliverables=["report.docx", "summary.txt"],
        max_tokens=250000,
        max_usd=1.0
    ),
    "generic_task": JobTemplate(
        id="generic_task",
        name="Generic Agent Task",
        complexity_class="Trivial",
        required_capabilities=["general"],
        permissions=ToolPermissionMatrix(
            allowed_tools=["*"],
            blocked_tools=["delete_file"],
            requires_approval=["run_command", "shell_exec"]
        ),
        expected_deliverables=[],
        max_tokens=50000,
        max_usd=0.2
    )
}

class NeuralRouter:
    """
    Acts as the entrypoint for the Autonomous Operator.
    Converts a free-form user query into a controlled, templated job execution block.
    """
    def __init__(self, agent_instance):
        self.agent = agent_instance
        
    async def route_request(self, original_input: str) -> JobTemplate:
        """
        Uses an LLM (or heuristics) to classify the user's intent into a specific JobTemplate.
        """
        logger.info(f"Routing request: {original_input[:50]}...")
        
        from core.multi_agent.golden_memory import golden_memory
        
        # 1. Semantic Routing (Golden Recipes / Vector Memory)
        semantic_match_id = await golden_memory.find_closest_template(original_input, self.agent)
        if semantic_match_id and semantic_match_id in TEMPLATES:
            selected = TEMPLATES[semantic_match_id]
            logger.info(f"Routed via Semantic Matrix -> template: {selected.name} (Complexity: {selected.complexity_class})")
            return selected
        
        # 2. Heuristic Routing Fallback
        lower_input = original_input.lower()
        if any(kw in lower_input for kw in ["web proje", "html", "css", "cam efektli", "portfolyo", "tasarla"]):
            selected = TEMPLATES["web_project_scaffold"]
        elif any(kw in lower_input for kw in ["araştır", "araştırma", "haber", "rapor", "özetle", "reasoning"]):
            selected = TEMPLATES["research_report"]
        else:
            selected = TEMPLATES["generic_task"]
            
        logger.info(f"Routed to template: {selected.name} (Complexity: {selected.complexity_class})")
        return selected

    def validate_tool_execution(self, template: JobTemplate, tool_name: str) -> tuple[bool, str]:
        """
        Validates if a tool can be executed within the boundaries of the selected JobTemplate.
        """
        if not template.permissions.can_execute(tool_name):
            return False, f"Tool '{tool_name}' is blocked or not explicitly allowed in job '{template.id}'"
            
        if template.permissions.needs_approval(tool_name):
            return False, f"Tool '{tool_name}' requires explicit user approval in job '{template.id}'"
            
        return True, ""
