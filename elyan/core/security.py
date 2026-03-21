from __future__ import annotations

from typing import Any

from elyan.approval.gate import check_approval
from elyan.sandbox.executor import SandboxExecutor, get_sandbox_executor
from elyan.sandbox.policy import SandboxConfig, default_sandbox_config, merge_sandbox_config, sandbox_config_for_action


class SecurityLayer:
    def __init__(self, sandbox: SandboxExecutor | None = None) -> None:
        self.sandbox = sandbox or get_sandbox_executor()

    async def authorize_action(
        self,
        skill_name: str,
        action: dict[str, Any],
        user_context: dict[str, Any] | None = None,
    ) -> bool:
        approved = await check_approval(skill_name, action, user_context or {})
        if not approved:
            raise PermissionError("Onay reddedildi")
        return True

    def _sandbox_config_for(self, skill_name: str, action: dict[str, Any], code: str, user_context: dict[str, Any]) -> SandboxConfig:
        payload = dict(action or {})
        context = dict(user_context or {})
        language = str(payload.get("language") or context.get("language") or "shell").strip().lower() or "shell"
        if not code and payload.get("code"):
            code = str(payload.get("code") or "")
        config = sandbox_config_for_action(
            {
                **payload,
                "language": language,
                "command": str(payload.get("command") or code or ""),
                "workspace_dir": str(payload.get("workspace_dir") or context.get("workspace_dir") or context.get("workspace") or ""),
                "needs_network": bool(payload.get("needs_network", context.get("needs_network", False))),
                "timeout": int(payload.get("timeout") or context.get("timeout") or 30),
                "env": dict(context.get("env") or payload.get("env") or {}),
                "volumes": dict(payload.get("volumes") or context.get("volumes") or {}),
            },
            skill_name=skill_name,
            default_language=language,
        )
        base = default_sandbox_config(language=language, command=str(code or payload.get("command") or ""))
        return merge_sandbox_config(base, config)

    async def execute_safe(
        self,
        skill_name: str,
        action: dict[str, Any],
        code: str,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.authorize_action(skill_name, action, user_context)
        payload = dict(action or {})
        command = str(code or payload.get("command") or payload.get("code") or "").strip()
        if not command:
            return {
                "success": True,
                "approved": True,
                "sandboxed": False,
                "skill_name": str(skill_name or ""),
                "action": payload,
                "status": "approved",
            }
        config = self._sandbox_config_for(skill_name, payload, command, dict(user_context or {}))
        result = await self.sandbox.run(command, config=config, timeout=int(config.timeout or 30))
        result.setdefault("approved", True)
        result.setdefault("skill_name", str(skill_name or ""))
        result.setdefault("action", payload)
        return result


_security_layer: SecurityLayer | None = None


def get_security_layer() -> SecurityLayer:
    global _security_layer
    if _security_layer is None:
        _security_layer = SecurityLayer()
    return _security_layer


security_layer = get_security_layer()

