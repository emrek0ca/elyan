"""
Tool Health Check and Dependency Management System
Monitors tool availability, dependency status, and fallback strategies
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("tool_health")


class ToolStatus(Enum):
    """Tool availability status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass
class ToolHealth:
    """Health status of a single tool"""
    name: str
    status: ToolStatus = ToolStatus.UNKNOWN
    last_checked: Optional[datetime] = None
    check_duration_ms: float = 0.0
    error_message: Optional[str] = None
    version: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    fallback_tools: List[str] = field(default_factory=list)

    def is_healthy(self) -> bool:
        """Check if tool is usable"""
        return self.status in [ToolStatus.HEALTHY, ToolStatus.DEGRADED]

    def age_seconds(self) -> float:
        """Age of health check in seconds"""
        if not self.last_checked:
            return float('inf')
        return (datetime.now() - self.last_checked).total_seconds()


class ToolHealthManager:
    """Manages health checks and status of all tools"""

    # Tools to health-check on startup
    CRITICAL_TOOLS = [
        "take_screenshot",
        "open_app",
        "list_files",
        "read_file",
    ]

    # macOS CLI tools that might be missing
    CLI_TOOLS = {
        "brightness": {
            "cmd": ["brightness", "get"],
            "fallback": "get_brightness",
        },
        "wifi": {
            "cmd": ["networksetup", "-getairportpower", "en0"],
            "fallback": "wifi_status",
        },
    }

    # Fallback tool mapping
    FALLBACKS = {
        "advanced_research": ["web_search", "fetch_page"],
        "read_pdf": ["read_file"],
        "read_word": ["read_file"],
        "summarize_document": ["read_file"],
        "analyze_document": ["read_file"],
        "spotlight_search": ["search_files"],
    }

    def __init__(self, cache_ttl_seconds: int = 30):
        self.cache_ttl = cache_ttl_seconds
        self.health_cache: Dict[str, ToolHealth] = {}
        self.initialized = False

    async def initialize(self):
        """Run health checks on startup"""
        if self.initialized:
            return

        logger.info("Initializing tool health checks...")

        # Quick health check on critical tools
        for tool_name in self.CRITICAL_TOOLS:
            await self.check_tool(tool_name)

        # Check CLI tool availability
        for cli_name in self.CLI_TOOLS:
            await self._check_cli_availability(cli_name)

        self.initialized = True
        logger.info("Tool health check initialization complete")

    async def check_tool(self, tool_name: str) -> ToolHealth:
        """Check health of a single tool"""
        # Check cache first
        cached = self.health_cache.get(tool_name)
        if cached and cached.age_seconds() < self.cache_ttl:
            return cached

        start = datetime.now()
        health = ToolHealth(name=tool_name)

        try:
            # Import available tools
            from tools import AVAILABLE_TOOLS

            if tool_name not in AVAILABLE_TOOLS:
                health.status = ToolStatus.UNAVAILABLE
                health.error_message = f"Tool '{tool_name}' not found in AVAILABLE_TOOLS"
                logger.warning(f"Tool {tool_name}: UNAVAILABLE - {health.error_message}")
            else:
                # Tool is available
                health.status = ToolStatus.HEALTHY
                health.fallback_tools = self.FALLBACKS.get(tool_name, [])
                logger.debug(f"Tool {tool_name}: HEALTHY")

        except Exception as e:
            health.status = ToolStatus.UNAVAILABLE
            health.error_message = str(e)
            logger.warning(f"Tool {tool_name}: UNAVAILABLE - {e}")

        health.last_checked = datetime.now()
        health.check_duration_ms = (datetime.now() - start).total_seconds() * 1000

        self.health_cache[tool_name] = health
        return health

    async def _check_cli_availability(self, cli_name: str):
        """Check if a CLI tool is available"""
        config = self.CLI_TOOLS.get(cli_name, {})
        cmd = config.get("cmd", [])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(process.wait(), timeout=2.0)

            logger.debug(f"CLI tool '{cli_name}': available")

        except asyncio.TimeoutError:
            logger.warning(f"CLI tool '{cli_name}': timeout")
        except (FileNotFoundError, OSError):
            logger.warning(f"CLI tool '{cli_name}': not found")
        except Exception as e:
            logger.debug(f"CLI tool '{cli_name}': check failed - {e}")

    def get_tool_status(self, tool_name: str) -> ToolStatus:
        """Get cached tool status without re-checking"""
        health = self.health_cache.get(tool_name)
        if health:
            return health.status
        return ToolStatus.UNKNOWN

    def get_tool_health(self, tool_name: str) -> Optional[ToolHealth]:
        """Get full health info for a tool"""
        return self.health_cache.get(tool_name)

    def get_available_tools(self) -> List[str]:
        """Get list of all available tools"""
        from tools import AVAILABLE_TOOLS
        return list(AVAILABLE_TOOLS.keys())

    def get_health_summary(self) -> Dict[str, Any]:
        """Get summary of tool health status"""
        total = 0
        healthy = 0
        degraded = 0
        unavailable = 0
        unknown = 0

        from tools import AVAILABLE_TOOLS

        for tool_name in AVAILABLE_TOOLS:
            total += 1
            health = self.health_cache.get(tool_name)

            if health:
                if health.status == ToolStatus.HEALTHY:
                    healthy += 1
                elif health.status == ToolStatus.DEGRADED:
                    degraded += 1
                elif health.status == ToolStatus.UNAVAILABLE:
                    unavailable += 1
                else:
                    unknown += 1
            else:
                unknown += 1

        return {
            "total_tools": total,
            "healthy": healthy,
            "degraded": degraded,
            "unavailable": unavailable,
            "unknown": unknown,
            "health_percentage": (healthy / total * 100) if total > 0 else 0,
        }

    def suggest_fallback(self, tool_name: str) -> Optional[str]:
        """Suggest a fallback tool if primary tool fails"""
        fallbacks = self.FALLBACKS.get(tool_name, [])

        if not fallbacks:
            return None

        # Return first available fallback
        for fallback in fallbacks:
            if self.get_tool_status(fallback) in [ToolStatus.HEALTHY, ToolStatus.DEGRADED]:
                return fallback

        # If no healthy fallback, return first one anyway (better than nothing)
        return fallbacks[0] if fallbacks else None

    async def validate_tool_params(self, tool_name: str, params: Dict) -> tuple[bool, Optional[str]]:
        """Validate if tool parameters are valid"""
        # For now, just check tool exists
        health = await self.check_tool(tool_name)

        if not health.is_healthy():
            return False, f"Tool '{tool_name}' is not available: {health.error_message}"

        return True, None

    def reset_cache(self):
        """Clear health check cache"""
        self.health_cache.clear()
        logger.info("Health check cache cleared")


# Global instance
_tool_health_manager: Optional[ToolHealthManager] = None


def get_tool_health_manager() -> ToolHealthManager:
    """Get or create tool health manager"""
    global _tool_health_manager
    if _tool_health_manager is None:
        _tool_health_manager = ToolHealthManager()
    return _tool_health_manager
