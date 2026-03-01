"""
Tool Policy Engine — Controls access to tools based on allow/deny lists.

FIX BUG-SEC-002:
- Deny list is always checked BEFORE allow list (deny-first)
- Group-level deny overrides tool-level allow
- requires_approval is enforced at check_access level
"""
import logging
from typing import Dict, List, Any, Optional
from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("tool_policy")

# Canonical defaults
_DEFAULT_ALLOW = [
    "group:fs",
    "group:web",
    "group:ui",
    "group:runtime",
    "group:messaging",
    "group:automation",
    "group:memory",
    "browser",
]
_DEFAULT_DENY: list[str] = []
_DEFAULT_REQUIRE_APPROVAL = ["exec", "delete_file"]

# Coarse tool-group hints to avoid `tool_group=None` bypass.
_TOOL_GROUP_HINTS: Dict[str, str] = {
    # fs
    "list_files": "fs",
    "read_file": "fs",
    "write_file": "fs",
    "search_files": "fs",
    "delete_file": "fs",
    "move_file": "fs",
    "copy_file": "fs",
    "rename_file": "fs",
    "create_folder": "fs",
    # runtime
    "run_command": "runtime",
    "run_safe_command": "runtime",
    "execute_command": "runtime",
    "execute_python": "runtime",
    "execute_python_code": "runtime",
    "execute_javascript_code": "runtime",
    "execute_shell_command": "runtime",
    "debug_code": "runtime",
    "open_app": "runtime",
    "close_app": "runtime",
    "type_text": "runtime",
    "press_key": "runtime",
    "key_combo": "runtime",
    "mouse_move": "runtime",
    "mouse_click": "runtime",
    "computer_use": "runtime",
    "get_system_info": "runtime",
    "get_process_info": "runtime",
    "get_running_apps": "runtime",
    # web/ui
    "web_search": "web",
    "fetch_page": "web",
    "extract_text": "web",
    "open_url": "ui",
    "take_screenshot": "ui",
    "create_visual_asset_pack": "ui",
    "analyze_and_narrate_image": "ui",
    # messaging
    "send_message": "messaging",
    "send_email": "messaging",
    "get_emails": "messaging",
    "get_unread_emails": "messaging",
    "search_emails": "messaging",
    "send_file": "messaging",
    "send_image": "messaging",
    # automation
    "create_event": "automation",
    "create_reminder": "automation",
    "cron_add": "automation",
    "cron_remove": "automation",
    "cron_list": "automation",
    # memory
    "memory_store": "memory",
    "memory_recall": "memory",
    "memory_search": "memory",
    "memory_forget": "memory",
    # analytics/visualization
    "create_chart": "web",
    "create_research_visualization": "web",
}


class ToolPolicyEngine:
    """Controls access to tools based on allow/deny lists and risk levels."""

    def __init__(self):
        self.allowed_tools: List[str] = []
        self.denied_tools: List[str] = []
        self.require_approval: List[str] = []
        self.reload()

    @staticmethod
    def _dedupe_clean(items: Any, default: list[str]) -> list[str]:
        if not isinstance(items, list):
            items = list(default)
        cleaned = []
        seen = set()
        for raw in items:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            cleaned.append(item)
        return cleaned

    def _load_policy_from_config(self) -> None:
        allow_raw = elyan_config.get("tools.allow", _DEFAULT_ALLOW)
        deny_raw = elyan_config.get("tools.deny", _DEFAULT_DENY)

        # Backward + roadmap compatibility
        require_raw = elyan_config.get("tools.require_approval", None)
        if require_raw is None:
            require_raw = elyan_config.get("tools.requireApproval", _DEFAULT_REQUIRE_APPROVAL)

        self.allowed_tools = self._dedupe_clean(allow_raw, _DEFAULT_ALLOW)
        self.denied_tools = self._dedupe_clean(deny_raw, _DEFAULT_DENY)
        self.require_approval = self._dedupe_clean(require_raw, _DEFAULT_REQUIRE_APPROVAL)

    def _is_denied(self, tool_name: str, tool_group: Optional[str] = None) -> bool:
        """Check if a tool is explicitly denied. Deny always wins."""
        if tool_name in self.denied_tools:
            return True
        if tool_group and f"group:{tool_group}" in self.denied_tools:
            return True
        # Wildcard deny
        if "*" in self.denied_tools:
            return True
        return False

    def _is_allowed(self, tool_name: str, tool_group: Optional[str] = None) -> bool:
        """Check if a tool is in the allow list."""
        if "*" in self.allowed_tools:
            return True
        if tool_name in self.allowed_tools:
            return True
        if tool_group and f"group:{tool_group}" in self.allowed_tools:
            return True
        return False

    def _infer_group(self, tool_name: str) -> Optional[str]:
        name = str(tool_name or "").strip().lower()
        if name in _TOOL_GROUP_HINTS:
            return _TOOL_GROUP_HINTS[name]
        # Heuristics for names not in static map
        if any(k in name for k in ("file", "folder", "path", "directory")):
            return "fs"
        if any(k in name for k in ("command", "process", "python", "exec", "terminal", "shell", "system", "app")):
            return "runtime"
        if any(k in name for k in ("web", "url", "browser", "fetch", "search")):
            return "web"
        if any(k in name for k in ("message", "email", "mail", "slack", "telegram", "discord")):
            return "messaging"
        if any(k in name for k in ("cron", "reminder", "event", "schedule", "heartbeat")):
            return "automation"
        if any(k in name for k in ("memory", "embedding", "context")):
            return "memory"
        return None

    def infer_group(self, tool_name: str) -> Optional[str]:
        """Public group inference for dashboard/API consumers."""
        return self._infer_group(tool_name)

    def is_allowed(self, tool_name: str, tool_group: Optional[str] = None) -> bool:
        """
        Check if a tool is allowed.
        DENY is always checked first — deny overrides allow.
        """
        if tool_group is None:
            tool_group = self._infer_group(tool_name)

        # 1. Deny check (always first)
        if self._is_denied(tool_name, tool_group):
            logger.debug(f"Tool '{tool_name}' denied by policy")
            return False
        # 2. Allow check
        if self._is_allowed(tool_name, tool_group):
            return True
        logger.debug(f"Tool '{tool_name}' not in allow list")
        return False

    def needs_approval(self, tool_name: str) -> bool:
        return tool_name in self.require_approval

    def check_access(self, tool_name: str, tool_group: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive access check.
        Returns dict with 'allowed' bool and optional 'requires_approval' bool.
        Callers MUST respect 'requires_approval' — it is not optional.
        """
        if tool_group is None:
            tool_group = self._infer_group(tool_name)

        if not self.is_allowed(tool_name, tool_group):
            return {"allowed": False, "requires_approval": False, "reason": "Policy restriction"}

        if self.needs_approval(tool_name) or (tool_group and f"group:{tool_group}" in self.require_approval):
            return {"allowed": True, "requires_approval": True, "reason": "Approval required by policy"}

        return {"allowed": True, "requires_approval": False, "reason": "OK"}

    def reload(self):
        """Reload policy from config (hot reload support)."""
        self._load_policy_from_config()
        logger.info("Tool policy reloaded")


# Global instance
tool_policy = ToolPolicyEngine()
