from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass, field
import asyncio
import inspect
from utils.logger import get_logger

logger = get_logger("registry")

@dataclass
class ToolDefinition:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]
    requires_approval: bool = False
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    evidence_adapter: Optional[Callable[[Any], Dict[str, Any]]] = None

class ToolRegistry:
    """Central repository for all agent capabilities."""
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._breakers: Dict[str, Any] = {}

    @staticmethod
    def _build_signature_schema(func: Callable) -> Dict[str, Any]:
        required: list[str] = []
        properties: Dict[str, Any] = {}
        try:
            sig = inspect.signature(func)
            for k, v in sig.parameters.items():
                if v.default == inspect.Parameter.empty:
                    required.append(k)
                ann = "Any"
                if v.annotation != inspect.Parameter.empty:
                    ann = str(v.annotation)
                properties[k] = {"type": ann}
        except Exception:
            pass
        return {"type": "object", "required": required, "properties": properties}

    def register(
        self,
        name: str,
        description: str = "",
        approval: bool = False,
        *,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        retry_policy: Optional[Dict[str, Any]] = None,
        evidence_adapter: Optional[Callable[[Any], Dict[str, Any]]] = None,
    ):
        """Decorator to register a function as a tool."""
        def decorator(func: Callable):
            sig = inspect.signature(func)
            params = {
                k: str(v.annotation) if v.annotation != inspect.Parameter.empty else "Any"
                for k, v in sig.parameters.items()
            }
            in_schema = dict(input_schema or self._build_signature_schema(func))
            out_schema = dict(output_schema or {"type": "object"})
            rp = dict(retry_policy or {"max_attempts": 1, "backoff_s": 0.0, "circuit_breaker": False})
            
            tool_def = ToolDefinition(
                name=name,
                description=description or func.__doc__ or "",
                func=func,
                parameters=params,
                requires_approval=approval,
                input_schema=in_schema,
                output_schema=out_schema,
                retry_policy=rp,
                evidence_adapter=evidence_adapter,
            )
            self._tools[name] = tool_def
            return func
        return decorator

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> Dict[str, str]:
        return {name: t.description for name, t in self._tools.items()}

    async def execute(self, tool_name: str, params: Dict[str, Any]) -> Any:
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        call_params = params if isinstance(params, dict) else {}
        schema = dict(tool.input_schema or {})
        if not schema:
            schema = {"type": "object", "required": [], "properties": {}}
            for k in tool.parameters.keys():
                schema["properties"][k] = {"type": str(tool.parameters.get(k) or "Any")}

        required = schema.get("required", []) if isinstance(schema.get("required"), list) else []
        missing = [str(k) for k in required if str(k) not in call_params]
        if missing:
            raise ValueError(f"Invalid parameters for {tool_name}: missing required keys {missing}")

        rp = dict(tool.retry_policy or {})
        max_attempts = max(1, int(rp.get("max_attempts", 1) or 1))
        backoff_s = max(0.0, float(rp.get("backoff_s", 0.0) or 0.0))
        use_circuit = bool(rp.get("circuit_breaker", False))
        breaker = None
        if use_circuit:
            try:
                from core.resilience.circuit_breaker import CircuitBreaker

                breaker = self._breakers.get(tool_name)
                if breaker is None:
                    breaker = CircuitBreaker(
                        failure_threshold=max(2, int(rp.get("failure_threshold", 3) or 3)),
                        recovery_timeout=max(5, int(rp.get("recovery_timeout_s", 60) or 60)),
                        half_open_max_requests=max(1, int(rp.get("half_open_max_requests", 2) or 2)),
                    )
                    self._breakers[tool_name] = breaker
            except Exception:
                breaker = None

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if breaker is not None and not breaker.can_execute():
                raise RuntimeError(f"Circuit open for tool: {tool_name}")

            try:
                if inspect.iscoroutinefunction(tool.func):
                    result = await tool.func(**call_params)
                else:
                    result = tool.func(**call_params)

                if breaker is not None:
                    breaker.record_success()
                if callable(tool.evidence_adapter):
                    try:
                        evidence = tool.evidence_adapter(result)
                        if isinstance(result, dict) and isinstance(evidence, dict):
                            result = dict(result)
                            result.setdefault("_evidence", evidence)
                    except Exception:
                        pass
                return result
            except TypeError as e:
                if breaker is not None:
                    breaker.record_failure()
                raise ValueError(f"Invalid parameters for {tool_name}: {e}")
            except Exception as e:
                last_error = e
                if breaker is not None:
                    breaker.record_failure()
                if attempt >= max_attempts:
                    logger.error(f"Tool Execution Error ({tool_name}) after {attempt} attempt(s): {e}")
                    raise
                if backoff_s > 0.0:
                    await asyncio.sleep(backoff_s * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Tool Execution Error ({tool_name}): unknown")

# Global Instance
registry = ToolRegistry()
# Alias for decorator
tool = registry.register
