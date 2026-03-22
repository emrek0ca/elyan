from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.observability.logger import get_structured_logger

slog = get_structured_logger("skill_registry")

class SkillDefinition(BaseModel):
    name: str
    description: str
    category: str
    tools: List[str] # List of tool names this skill uses
    system_prompt_snippet: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SkillRegistry:
    """
    Registry for Elyan Skills (behavior templates).
    """
    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}

    def register_skill(self, skill: SkillDefinition):
        self._skills[skill.name] = skill
        slog.log_event("skill_registered", {"name": skill.name, "category": skill.category})

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        return self._skills.get(name)

    def list_skills(self, category: Optional[str] = None) -> List[SkillDefinition]:
        if category:
            return [s for s in self._skills.values() if s.category == category]
        return list(self._skills.values())

# Global instance
skill_registry = SkillRegistry()

# Initialize with core skills
def _init_core_skills():
    core_skills = [
        SkillDefinition(
            name="file_ops",
            description="Advanced file manipulation and organization",
            category="files",
            tools=["filesystem.list_directory", "filesystem.read_file", "filesystem.write_file"],
            system_prompt_snippet="You are a file management expert. Use filesystem tools to organize and edit files safely."
        ),
        SkillDefinition(
            name="dev_ops",
            description="System inspection and command execution",
            category="system",
            tools=["terminal.execute"],
            system_prompt_snippet="You are a DevOps engineer. Use the terminal to inspect and manage system state."
        )
    ]
    for skill in core_skills:
        skill_registry.register_skill(skill)

_init_core_skills()
