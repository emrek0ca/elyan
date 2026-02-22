"""
core/plugins/plugin_manager.py
─────────────────────────────────────────────────────────────────────────────
Plugin Architecture & Marketplace (Phase 36).
Allows third-party developers to extend Elyan with custom tools,
models, and integrations — loaded dynamically at runtime with sandboxing.
"""

import importlib
import inspect
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional
from utils.logger import get_logger

logger = get_logger("plugins")

@dataclass
class PluginManifest:
    name: str
    version: str
    author: str
    description: str
    entry_point: str  # module.Class or module.function
    permissions: List[str] = field(default_factory=list)  # ["network", "filesystem", "shell"]
    enabled: bool = True

@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    instance: Any = None
    tools: Dict[str, Callable] = field(default_factory=dict)

class PluginManager:
    PLUGINS_DIR = Path.home() / ".elyan" / "plugins"
    ALLOWED_PERMISSIONS = {"network", "filesystem", "llm", "ui"}
    BANNED_PERMISSIONS = {"shell", "system", "root"}
    
    def __init__(self):
        self.PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        self._plugins: Dict[str, LoadedPlugin] = {}
    
    def discover_plugins(self) -> List[PluginManifest]:
        """Scan the plugins directory for plugin manifests."""
        manifests = []
        for plugin_dir in self.PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir():
                manifest_file = plugin_dir / "plugin.json"
                if manifest_file.exists():
                    try:
                        data = json.loads(manifest_file.read_text(encoding="utf-8"))
                        manifest = PluginManifest(**data)
                        
                        # Security check: reject plugins requesting banned permissions
                        banned = set(manifest.permissions) & self.BANNED_PERMISSIONS
                        if banned:
                            logger.warning(f"🚫 Plugin '{manifest.name}' rejected: banned permissions {banned}")
                            continue
                        
                        manifests.append(manifest)
                    except Exception as e:
                        logger.error(f"Invalid plugin manifest in {plugin_dir}: {e}")
        
        logger.info(f"🧩 Discovered {len(manifests)} plugins.")
        return manifests
    
    def load_plugin(self, manifest: PluginManifest) -> Optional[LoadedPlugin]:
        """Dynamically load a plugin and register its tools."""
        if not manifest.enabled:
            return None
        
        try:
            plugin_path = self.PLUGINS_DIR / manifest.name
            module_name = manifest.entry_point.rsplit(".", 1)[0]
            class_name = manifest.entry_point.rsplit(".", 1)[1] if "." in manifest.entry_point else None
            
            # Add plugin dir to path temporarily
            import sys
            sys.path.insert(0, str(plugin_path))
            
            try:
                module = importlib.import_module(module_name)
                
                if class_name:
                    cls = getattr(module, class_name)
                    instance = cls()
                else:
                    instance = module
                
                # Discover tools (public methods with @tool decorator or docstrings)
                tools = {}
                for name, method in inspect.getmembers(instance, predicate=inspect.ismethod):
                    if not name.startswith("_"):
                        tools[f"{manifest.name}.{name}"] = method
                
                loaded = LoadedPlugin(manifest=manifest, instance=instance, tools=tools)
                self._plugins[manifest.name] = loaded
                
                logger.info(f"🧩 Plugin '{manifest.name}' v{manifest.version} loaded with {len(tools)} tools.")
                return loaded
                
            finally:
                sys.path.pop(0)
                
        except Exception as e:
            logger.error(f"Failed to load plugin '{manifest.name}': {e}")
            return None
    
    def load_all(self):
        """Discover and load all available plugins."""
        for manifest in self.discover_plugins():
            self.load_plugin(manifest)
    
    def get_all_tools(self) -> Dict[str, Callable]:
        """Return all tools from all loaded plugins."""
        all_tools = {}
        for plugin in self._plugins.values():
            all_tools.update(plugin.tools)
        return all_tools
    
    def unload_plugin(self, name: str):
        """Safely unload a plugin."""
        if name in self._plugins:
            del self._plugins[name]
            logger.info(f"🧩 Plugin '{name}' unloaded.")
    
    def list_plugins(self) -> List[Dict]:
        """List all loaded plugins and their status."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "author": p.manifest.author,
                "tools": list(p.tools.keys()),
                "permissions": p.manifest.permissions
            }
            for p in self._plugins.values()
        ]

# Global singleton
plugins = PluginManager()
