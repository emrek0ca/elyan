"""
Elyan RBAC — Role-Based Access Control

Admin, operator, viewer roles with tool access restrictions.
"""

from typing import Any, Dict, List, Optional, Set
from utils.logger import get_logger

logger = get_logger("rbac")


class Role:
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


# Tool access by role
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    Role.ADMIN: {"*"},  # Full access
    Role.OPERATOR: {
        "read_file", "write_file", "list_files", "search_files", "create_folder",
        "run_command", "run_safe_command", "run_code",
        "web_search", "fetch_page", "start_research",
        "git_clone", "git_status", "git_commit", "git_push", "git_pull",
        "db_execute", "db_schema",
        "http_request", "analyze_data",
        "pip_install", "npm_install",
        "docker_build", "docker_run", "docker_ps",
        "deploy_to_vercel", "deploy_to_netlify",
        "create_chart", "generate_report",
        "send_email",
    },
    Role.VIEWER: {
        "read_file", "list_files", "search_files",
        "web_search", "fetch_page",
        "db_schema", "read_csv", "read_json",
        "get_system_info", "get_battery_status",
        "api_health_check",
    },
}


class RBAC:
    """Role-Based Access Control manager."""

    def __init__(self):
        self.user_roles: Dict[str, str] = {}
        self.default_role = Role.OPERATOR

    def set_role(self, user_id: str, role: str):
        """Assign a role to a user."""
        if role not in (Role.ADMIN, Role.OPERATOR, Role.VIEWER):
            raise ValueError(f"Invalid role: {role}")
        self.user_roles[user_id] = role
        logger.info(f"User {user_id} assigned role: {role}")

    def get_role(self, user_id: str) -> str:
        return self.user_roles.get(user_id, self.default_role)

    def check_permission(self, user_id: str, tool_name: str) -> bool:
        """Check if user has permission to use a tool."""
        role = self.get_role(user_id)
        permissions = ROLE_PERMISSIONS.get(role, set())
        if "*" in permissions:
            return True
        return tool_name in permissions

    def get_allowed_tools(self, user_id: str) -> Set[str]:
        """Get all tools a user can access."""
        role = self.get_role(user_id)
        return ROLE_PERMISSIONS.get(role, set())

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_users": len(self.user_roles),
            "roles": {role: sum(1 for r in self.user_roles.values() if r == role) 
                     for role in (Role.ADMIN, Role.OPERATOR, Role.VIEWER)},
            "default_role": self.default_role,
        }


# Global instance
rbac = RBAC()
