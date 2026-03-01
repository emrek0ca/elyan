from typing import Optional, Any
import inspect
from utils.logger import get_logger

logger = get_logger("kernel")

class Kernel:
    """Service Locator / Container for Elyan Core Services."""
    
    _instance = None

    def __init__(self):
        # Lazy imports to break circularity
        from config.elyan_config import elyan_config
        from core.registry import registry
        from core.memory import memory
        
        self.config = elyan_config
        self.tools = registry
        self.memory = memory
        self.llm = None
        self._initialized = False

    async def initialize(self):
        if self._initialized: return
        
        logger.info("Kernel initializing...")
        from core.llm_client import LLMClient
        self.llm = LLMClient()
        
        # Discovery: register decorated tools + lazily exported tool functions
        from tools import system_tools
        added, skipped = self._auto_register_lazy_tools()
        logger.info(f"Tool auto-registration: +{added} (unavailable: {skipped})")
        
        logger.info(f"Loaded {len(self.tools.list_tools())} tools.")
        self._initialized = True

    def _auto_register_lazy_tools(self) -> tuple[int, int]:
        """
        Bridge legacy @tool registry with AVAILABLE_TOOLS lazy catalog.
        This keeps planner/registry visibility in sync with executable tools.
        """
        from core.registry import ToolDefinition
        from core.evidence.adapters import adapt_evidence
        from tools import AVAILABLE_TOOLS

        added = 0
        skipped = 0
        for name in sorted(AVAILABLE_TOOLS.keys()):
            if self.tools.get_tool(name):
                continue

            func = AVAILABLE_TOOLS.get(name)
            if not callable(func):
                skipped += 1
                continue

            try:
                sig = inspect.signature(func)
                parameters = {
                    p_name: (
                        str(param.annotation)
                        if param.annotation != inspect.Parameter.empty
                        else "Any"
                    )
                    for p_name, param in sig.parameters.items()
                }
            except Exception:
                parameters = {}

            required = []
            try:
                sig2 = inspect.signature(func)
                for p_name, param in sig2.parameters.items():
                    if param.default == inspect.Parameter.empty:
                        required.append(p_name)
            except Exception:
                required = []
            input_schema = {
                "type": "object",
                "required": required,
                "properties": {k: {"type": str(v)} for k, v in parameters.items()},
            }

            desc = (getattr(func, "__doc__", "") or "").strip()
            if not desc:
                desc = f"{name} tool"

            self.tools._tools[name] = ToolDefinition(  # noqa: SLF001 - registry extension bridge
                name=name,
                description=desc,
                func=func,
                parameters=parameters,
                requires_approval=False,
                input_schema=input_schema,
                output_schema={"type": "object"},
                retry_policy={"max_attempts": 2, "backoff_s": 0.25, "circuit_breaker": name in {"http_request", "graphql_query", "api_health_check"}},
                evidence_adapter=(lambda result, _name=name: adapt_evidence(_name, result if isinstance(result, dict) else {})),
            )
            added += 1

        return added, skipped

    @classmethod
    def get(cls):
        if not cls._instance:
            cls._instance = Kernel()
        return cls._instance

# Global Accessor
kernel = Kernel.get()
