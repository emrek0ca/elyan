"""Email skill - wraps email tools."""

from typing import List, Dict, Any
from core.skills.base import BaseSkill


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
                from tools.email_tools import send_email
                to = params.get("to", "")
                subject = params.get("subject", "")
                body = params.get("body", "")
                result = await send_email(to=to, subject=subject, body=body)
                return {"success": True, "result": result}
            elif command == "check":
                from tools.email_tools import check_inbox
                result = await check_inbox()
                return {"success": True, "result": result}
            else:
                return {"success": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_commands(self) -> List[Dict[str, Any]]:
        return [
            {"name": "send", "description": "E-posta gonder", "params": ["to", "subject", "body"]},
            {"name": "check", "description": "Gelen kutusunu kontrol et", "params": []},
        ]
