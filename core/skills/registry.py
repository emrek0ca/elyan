from __future__ import annotations

from typing import Dict, Optional

from core.skills.manager import skill_manager


class SkillRegistry:
    """
    Lightweight command->skill index.
    """

    def __init__(self):
        self.command_map: Dict[str, str] = {}

    def rebuild_command_map(self):
        self.command_map.clear()
        for item in skill_manager.list_skills(available=False, enabled_only=True):
            skill_name = str(item.get("name", "")).strip()
            for cmd in item.get("commands", []) or []:
                c = str(cmd or "").strip().lower()
                if c:
                    self.command_map[c] = skill_name

    def get_skill_for_command(self, command_name: str) -> Optional[dict]:
        if not self.command_map:
            self.rebuild_command_map()
        skill_name = self.command_map.get(str(command_name or "").strip().lower())
        if not skill_name:
            return None
        return skill_manager.get_skill(skill_name)


skill_registry = SkillRegistry()
