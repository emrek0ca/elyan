from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from core.runtime.tool_registry import ToolDefinition
from core.runtime.skill_registry import SkillDefinition

class PluginManifest(BaseModel):
    """
    Standard contract for an Elyan Plugin.
    A plugin can provide tools, skills, or even entire new capabilities.
    """
    plugin_id: str
    version: str
    author: str
    description: str
    
    # Optional extensions
    tools: List[ToolDefinition] = Field(default_factory=list)
    skills: List[SkillDefinition] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    
    # Configuration requirements
    required_env_vars: List[str] = Field(default_factory=list)
    default_config: Dict[str, Any] = Field(default_factory=dict)

class PluginStore:
    """
    Manages installed and active plugins.
    """
    def __init__(self):
        self._plugins: Dict[str, PluginManifest] = {}

    def install_plugin(self, manifest: PluginManifest):
        self._plugins[manifest.plugin_id] = manifest
        # Register tools and skills automatically
        from core.runtime.tool_registry import tool_registry
        from core.runtime.skill_registry import skill_registry
        
        for tool in manifest.tools:
            tool_registry.register_tool(tool)
        for skill in manifest.skills:
            skill_registry.register_skill(skill)
            
        print(f"Plugin {manifest.plugin_id} v{manifest.version} installed.")

# Global instance
plugin_store = PluginStore()
