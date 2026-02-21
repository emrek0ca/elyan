"""
Intelligent Request Router
Routes different types of requests to optimal tools and strategies
"""

from typing import Dict, List, Optional, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("request_router")


class RequestType(Enum):
    """Types of user requests"""
    FILE_OPERATION = "file_operation"
    RESEARCH = "research"
    DOCUMENT_PROCESSING = "document"
    SYSTEM_CONTROL = "system"
    CHAT = "chat"
    BATCH = "batch"
    UNKNOWN = "unknown"


class RoutingStrategy(Enum):
    """Routing strategies"""
    DIRECT = "direct"  # Single tool execution
    BATCH = "batch"  # Parallel multi-file processing
    SEQUENTIAL = "sequential"  # Step-by-step with context
    ADAPTIVE = "adaptive"  # Select best approach dynamically
    FALLBACK = "fallback"  # Use alternatives if primary fails


class Route:
    """Routing decision"""

    def __init__(
        self,
        request_type: RequestType,
        strategy: RoutingStrategy,
        primary_tool: str,
        alternative_tools: List[str] = None,
        metadata: Dict[str, Any] = None
    ):
        self.request_type = request_type
        self.strategy = strategy
        self.primary_tool = primary_tool
        self.alternative_tools = alternative_tools or []
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.request_type.value,
            "strategy": self.strategy.value,
            "primary": self.primary_tool,
            "alternatives": self.alternative_tools,
            "metadata": self.metadata
        }


class RequestRouter:
    """Routes requests to appropriate tools and strategies"""

    def __init__(self):
        self.routing_rules = self._initialize_rules()

    def _initialize_rules(self) -> Dict[RequestType, Dict[str, Any]]:
        """Initialize routing rules"""
        return {
            RequestType.FILE_OPERATION: {
                "keywords": ["file", "dosya", "read", "write", "oku", "yaz", "sil", "delete", "tasi", "move"],
                "primary": "file_operation",
                "strategy": RoutingStrategy.DIRECT,
                "supports_batch": True
            },
            RequestType.RESEARCH: {
                "keywords": ["research", "arastir", "web", "internet", "search", "ara", "information"],
                "primary": "advanced_research",
                "strategy": RoutingStrategy.ADAPTIVE,
                "supports_batch": False,
                "cache_ttl": 86400  # 24 hours
            },
            RequestType.DOCUMENT_PROCESSING: {
                "keywords": ["document", "belge", "pdf", "word", "excel", "summarize", "analyze", "extract"],
                "primary": "document_processing",
                "strategy": RoutingStrategy.BATCH,
                "supports_batch": True,
                "cache_ttl": 86400
            },
            RequestType.SYSTEM_CONTROL: {
                "keywords": ["system", "app", "application", "screenshot", "volume", "brightness", "dark mode"],
                "primary": "system_control",
                "strategy": RoutingStrategy.DIRECT,
                "supports_batch": False
            },
            RequestType.CHAT: {
                "keywords": ["hello", "merhaba", "how", "what", "nasil", "ne", "explain", "tell"],
                "primary": "chat",
                "strategy": RoutingStrategy.DIRECT,
                "supports_batch": False
            }
        }

    def route(self, user_input: str, file_count: int = 0) -> Route:
        """Route user request to appropriate tool"""
        request_type = self._classify_request(user_input)

        # Special handling for batch operations
        if file_count > 1 and request_type == RequestType.FILE_OPERATION:
            logger.info(f"Routing batch operation: {file_count} files")
            return Route(
                request_type=RequestType.BATCH,
                strategy=RoutingStrategy.BATCH,
                primary_tool="batch_processor",
                alternative_tools=["file_operation"],
                metadata={"file_count": file_count}
            )

        rule = self.routing_rules.get(request_type, {})
        strategy = rule.get("strategy", RoutingStrategy.DIRECT)
        primary = rule.get("primary", "agent_loop")
        alternatives = self._get_alternatives(request_type)

        logger.info(f"Routed {request_type.value} request with {strategy.value} strategy")

        return Route(
            request_type=request_type,
            strategy=strategy,
            primary_tool=primary,
            alternative_tools=alternatives,
            metadata=rule.get("metadata", {})
        )

    def _classify_request(self, user_input: str) -> RequestType:
        """Classify request type based on content"""
        user_input_lower = user_input.lower()

        # Check each category
        for req_type, rule in self.routing_rules.items():
            keywords = rule.get("keywords", [])
            if any(keyword in user_input_lower for keyword in keywords):
                return req_type

        return RequestType.UNKNOWN

    def _get_alternatives(self, request_type: RequestType) -> List[str]:
        """Get alternative tools for request type"""
        alternatives_map = {
            RequestType.FILE_OPERATION: ["list_files", "search_files"],
            RequestType.RESEARCH: ["web_search", "fetch_page"],
            RequestType.DOCUMENT_PROCESSING: ["read_file", "text_edit"],
            RequestType.SYSTEM_CONTROL: ["get_system_info", "take_screenshot"],
            RequestType.CHAT: ["agent_loop"]
        }
        return alternatives_map.get(request_type, [])

    def suggest_optimization(self, route: Route, operation_count: int) -> Dict[str, Any]:
        """Suggest optimizations for the route"""
        suggestions = {
            "strategy": route.strategy.value,
            "parallel_execution": operation_count > 1 and route.strategy in [RoutingStrategy.BATCH],
            "caching_recommended": route.strategy in [RoutingStrategy.ADAPTIVE],
            "timeout_seconds": 60
        }

        # Adjust suggestions based on operation type
        if route.request_type == RequestType.RESEARCH:
            suggestions["timeout_seconds"] = 120
            suggestions["caching_recommended"] = True
            suggestions["cache_ttl"] = 86400

        elif route.request_type == RequestType.DOCUMENT_PROCESSING:
            suggestions["timeout_seconds"] = 90
            suggestions["parallel_execution"] = True
            suggestions["max_parallel"] = 4

        elif route.request_type == RequestType.BATCH:
            suggestions["max_parallel"] = 4
            suggestions["timeout_per_file"] = 30

        return suggestions


# Global instance
_router: Optional[RequestRouter] = None


def get_request_router() -> RequestRouter:
    """Get or create request router"""
    global _router
    if _router is None:
        _router = RequestRouter()
    return _router
