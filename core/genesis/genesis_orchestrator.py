"""
Elyan Genesis Orchestrator — Central management for all Genesis modules

Coordinates adaptive learning, self-diagnostic, context fusion,
bio symbiosis, preemptive subconscious, evo compiler, and tool author.
"""

import time
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("genesis_orchestrator")


class GenesisOrchestrator:
    """Central coordinator for Genesis self-evolution modules."""

    def __init__(self):
        self.modules = {}
        self.active = False
        self.last_cycle = 0
        self.cycle_count = 0

    def register(self, name: str, module):
        """Register a Genesis module."""
        self.modules[name] = module
        logger.info(f"Genesis module registered: {name}")

    async def initialize(self):
        """Load and register all Genesis modules."""
        module_map = {
            "adaptive_learning": ("core.genesis.adaptive_learning", "AdaptiveLearning"),
            "self_diagnostic": ("core.genesis.self_diagnostic", "SelfDiagnostic"),
            "context_fusion": ("core.genesis.context_fusion", "ContextFusion"),
            "bio_symbiosis": ("core.genesis.bio_symbiosis", "BioSymbiosis"),
            "preemptive_sub": ("core.genesis.preemptive_subconscious", "PreemptiveSubconscious"),
            "evo_compiler": ("core.genesis.evo_compiler", "EvoCompiler"),
            "tool_author": ("core.genesis.tool_author", "ToolAuthor"),
        }

        for name, (module_path, class_name) in module_map.items():
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name, None)
                if cls:
                    instance = cls()
                    self.register(name, instance)
            except Exception as e:
                logger.warning(f"Failed to load Genesis module '{name}': {e}")

        self.active = True
        logger.info(f"Genesis Orchestrator initialized with {len(self.modules)} modules")

    async def run_cycle(self, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run a full Genesis evolution cycle."""
        if not self.active:
            await self.initialize()

        self.cycle_count += 1
        self.last_cycle = time.time()
        results = {}

        # Self-diagnostic
        if "self_diagnostic" in self.modules:
            try:
                diag = self.modules["self_diagnostic"]
                if hasattr(diag, "run_check"):
                    results["diagnostic"] = await diag.run_check()
            except Exception as e:
                results["diagnostic"] = {"error": str(e)}

        # Adaptive learning update
        if "adaptive_learning" in self.modules and context:
            try:
                al = self.modules["adaptive_learning"]
                if hasattr(al, "record_interaction"):
                    al.record_interaction(
                        context.get("user_id", "unknown"),
                        context.get("tool_used"),
                        context.get("message_length", 0),
                    )
                    results["adaptive"] = {"recorded": True}
            except Exception as e:
                results["adaptive"] = {"error": str(e)}

        return {
            "cycle": self.cycle_count,
            "modules_active": len(self.modules),
            "results": results,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "modules": list(self.modules.keys()),
            "module_count": len(self.modules),
            "cycles_completed": self.cycle_count,
            "last_cycle": self.last_cycle,
        }


# Global instance
genesis = GenesisOrchestrator()
