"""Email skill - wraps email tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill
from core.skills.tool_runtime import execute_registered_tool, wrap_skill_tool_result


class EmailSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "email"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "E-posta gonderme ve okuma islemleri"

    @property
    def required_tools(self) -> List[str]:
        return ["send_email"]

    async def setup(self) -> bool:
        return True

    async def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = context.get("params", {})

            if command == "send":
                to = params.get("to", "")
                subject = params.get("subject", "")
                body = params.get("body", "")
                result = await execute_registered_tool(
                    "send_email",
                    {"to": to, "subject": subject, "body": body},
                    source="builtin_email_skill",
                )
                return wrap_skill_tool_result(result)
            elif command == "check":
                result = await execute_registered_tool("get_unread_emails", {}, source="builtin_email_skill")
                return wrap_skill_tool_result(result)
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "send", "description": "E-posta gonder", "params": ["to", "subject", "body"]},
            {"name": "check", "description": "Gelen kutusunu kontrol et", "params": []},
        ]
