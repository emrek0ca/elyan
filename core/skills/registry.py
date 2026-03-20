from __future__ import annotations

from typing import Any, Dict, Optional

from core.capability_router import CapabilityRouter
from core.skills.manager import skill_manager


class SkillRegistry:
    """
    Lightweight command->skill index.
    """

    def __init__(self):
        self.command_map: Dict[str, str] = {}
        self._router = CapabilityRouter()

    def rebuild_command_map(self):
        self.command_map.clear()
        for item in skill_manager.list_skills(available=True, enabled_only=True):
            skill_name = str(item.get("name", "")).strip()
            for cmd in item.get("commands", []) or []:
                c = str(cmd or "").strip().lower()
                if c:
                    self.command_map[c] = skill_name

    def refresh(self) -> None:
        self.rebuild_command_map()

    def list_skills(self, *, available: bool = False, enabled_only: bool = False, query: str = "") -> list[dict[str, Any]]:
        return skill_manager.list_skills(available=available, enabled_only=enabled_only, query=query)

    def list_workflows(self, *, enabled_only: bool = False, query: str = "") -> list[dict[str, Any]]:
        return skill_manager.list_workflows(enabled_only=enabled_only, query=query)

    def get_skill(self, name: str) -> Optional[dict]:
        return skill_manager.get_skill(name)

    def manifest_from_skill(self, name: str) -> Optional[dict]:
        return skill_manager.manifest_from_skill(name)

    def get_skill_for_command(self, command_name: str) -> Optional[dict]:
        if not self.command_map:
            self.rebuild_command_map()
        skill_name = self.command_map.get(str(command_name or "").strip().lower())
        if not skill_name:
            return None
        return skill_manager.get_skill(skill_name)

    def _skill_from_domain(self, domain: str) -> Optional[dict]:
        normalized = str(domain or "").strip().lower()
        if not normalized:
            return None
        aliases = {
            "real_time_control": "system",
            "screen_operator": "system",
            "desktop_control": "system",
            "file_ops": "files",
            "document": "office",
            "browser": "browser",
            "website": "browser",
            "research": "research",
            "api_integration": "research",
            "email": "email",
            "calendar": "calendar",
            "social": "browser",
            "scheduler": "calendar",
            "google": "browser",
            "drive": "office",
            "code": "office",
            "automation": "system",
        }
        skill_name = aliases.get(normalized, normalized)
        return skill_manager.get_skill(skill_name)

    def resolve_from_intent(
        self,
        intent: Any,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = dict(request_context or {})
        text = ""
        if isinstance(intent, dict):
            text = str(intent.get("text") or intent.get("input_text") or intent.get("user_input") or intent.get("request") or "").strip()
        else:
            text = str(intent or "").strip()
        route = self._router.route(text)
        request_contract = self._router.build_request_contract(
            text,
            domain=str(route.domain or ""),
            confidence=float(route.confidence or 0.0),
            route_mode=str(route.suggested_job_type or ""),
            output_artifacts=list(route.output_artifacts or []),
            quality_checklist=list(route.quality_checklist or []),
            quick_intent=context.get("quick_intent"),
            parsed_intent=context.get("parsed_intent"),
            attachments=list(context.get("attachments") or []),
            metadata=context,
        )
        skill = self._skill_from_domain(route.domain)
        low_text = text.lower()
        browserish = any(
            marker in low_text
            for marker in (
                "http://",
                "https://",
                ".com",
                ".net",
                ".org",
                "www.",
                "browser",
                "safari",
                "chrome",
                "firefox",
                "web",
                "site",
                "visit",
                "go to",
            )
        )
        if browserish and (skill is None or str(skill.get("name") or "").strip().lower() in {"system", "files"}):
            browser_skill = skill_manager.get_skill("browser")
            if browser_skill:
                skill = browser_skill
        if skill is None:
            command = str((intent or {}).get("action") if isinstance(intent, dict) else "").strip().lower()
            if command:
                skill = self.get_skill_for_command(command)
        if skill is None:
            skill = self._skill_from_domain(str(context.get("capability_domain") or ""))
        skill_manifest = skill_manager.manifest_from_skill(str(skill.get("name") or "")) if skill else None
        workflows = skill_manager.list_workflows(enabled_only=True)
        workflow = None
        for item in workflows:
            triggers = [str(token).strip().lower() for token in list(item.get("trigger_markers") or []) if str(token).strip()]
            if any(marker and marker in text.lower() for marker in triggers):
                workflow = item
                break
        if workflow is None and str(route.domain or "") in {"screen_operator", "file_ops", "research", "code"}:
            matching = [item for item in workflows if str(item.get("category") or "").strip().lower() == str(route.domain or "").strip().lower()]
            workflow = matching[0] if matching else None

        integration: dict[str, Any] = {}
        try:
            from integrations.registry import integration_registry

            integration = integration_registry.resolve(
                {
                    "text": text,
                    "input_text": text,
                    "request": text,
                    "action": str((intent or {}).get("action") if isinstance(intent, dict) else ""),
                },
                {
                    **context,
                    "route": route.model_dump() if hasattr(route, "model_dump") else (route.to_dict() if hasattr(route, "to_dict") else dict(route.__dict__)),
                    "skill": skill_manifest or {},
                    "workflow": dict(workflow or {}),
                },
            ).model_dump()
        except Exception:
            integration = {}

        return {
            "text": text,
            "request_contract": request_contract.to_dict() if hasattr(request_contract, "to_dict") else dict(request_contract),
            "skill": skill_manifest,
            "workflow": dict(workflow or {}),
            "integration": dict(integration or {}),
            "workflow_bundle": dict((integration or {}).get("workflow_bundle") or {}),
            "route": route.model_dump() if hasattr(route, "model_dump") else (route.to_dict() if hasattr(route, "to_dict") else dict(route.__dict__)),
            "confidence": float(route.confidence or 0.0),
            "learning_tags": list(getattr(route, "learning_tags", []) or []),
            "latency_level": str((skill_manifest or {}).get("latency_level") or "standard"),
            "evidence_contract": dict((skill_manifest or {}).get("evidence_contract") or {}),
            "runtime_ready": bool((skill_manifest or {}).get("runtime_ready", False)),
            "approval_tools": list((skill_manifest or {}).get("approval_tools") or []),
            "integration_type": str((integration or {}).get("integration_type") or ""),
            "required_scopes": list((integration or {}).get("required_scopes") or []),
            "fallback_policy": str((integration or {}).get("fallback_policy") or ""),
            "real_time": bool((integration or {}).get("real_time", False)),
            "approval_level": int((integration or {}).get("approval_level") or 0),
        }


skill_registry = SkillRegistry()
