from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from config.elyan_config import elyan_config


@dataclass
class RuntimePolicy:
    name: str = "custom"
    flags: Dict[str, Any] = field(default_factory=dict)
    capability: Dict[str, Any] = field(default_factory=dict)
    planning: Dict[str, Any] = field(default_factory=dict)
    orchestration: Dict[str, Any] = field(default_factory=dict)
    api_tools: Dict[str, Any] = field(default_factory=dict)
    skills: Dict[str, Any] = field(default_factory=dict)
    tools: Dict[str, Any] = field(default_factory=dict)
    security: Dict[str, Any] = field(default_factory=dict)
    response: Dict[str, Any] = field(default_factory=dict)


class RuntimePolicyResolver:
    @staticmethod
    def _as_list(value: Any, default: list[str]) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return list(default)

    PRESETS: Dict[str, Dict[str, Any]] = {
        "strict": {
            "agent.capability_router.enabled": True,
            "agent.capability_router.min_confidence_override": 0.7,
            "agent.planning.use_llm": True,
            "agent.planning.max_subtasks": 8,
            "agent.multi_agent.enabled": True,
            "agent.multi_agent.complexity_threshold": 0.95,
            "agent.multi_agent.capability_confidence_threshold": 0.85,
            "agent.api_tools.enabled": False,
            "security.operatorMode": "Confirmed",
            "security.defaultUserRole": "viewer",
            "security.enforceRBAC": True,
            "security.pathGuard.enabled": True,
            "security.enableDangerousTools": False,
            "security.requireConfirmationForRisky": True,
            "security.kvkk.strict": True,
            "security.kvkk.redactCloudPrompts": True,
            "security.kvkk.allowCloudFallback": False,
            "tools.requireApproval": ["group:runtime", "group:fs", "delete_file", "write_file"],
            "agent.response_style.mode": "formal",
            "agent.response_style.friendly": False,
            "agent.response_style.share_manifest_default": True,
            "agent.response_style.share_attachments_default": True,
        },
        "balanced": {
            "agent.capability_router.enabled": True,
            "agent.capability_router.min_confidence_override": 0.5,
            "agent.planning.use_llm": True,
            "agent.planning.max_subtasks": 10,
            "agent.multi_agent.enabled": True,
            "agent.multi_agent.complexity_threshold": 0.9,
            "agent.multi_agent.capability_confidence_threshold": 0.7,
            "agent.api_tools.enabled": True,
            "security.operatorMode": "Confirmed",
            "security.defaultUserRole": "operator",
            "security.enforceRBAC": True,
            "security.pathGuard.enabled": True,
            "security.enableDangerousTools": True,
            "security.requireConfirmationForRisky": True,
            "security.kvkk.strict": True,
            "security.kvkk.redactCloudPrompts": True,
            "security.kvkk.allowCloudFallback": True,
            "tools.requireApproval": ["delete_file", "write_file"],
            "agent.response_style.mode": "friendly",
            "agent.response_style.friendly": True,
            "agent.response_style.share_manifest_default": False,
            "agent.response_style.share_attachments_default": False,
        },
        "full-autonomy": {
            "agent.capability_router.enabled": True,
            "agent.capability_router.min_confidence_override": 0.35,
            "agent.planning.use_llm": True,
            "agent.planning.max_subtasks": 14,
            "agent.multi_agent.enabled": True,
            "agent.multi_agent.complexity_threshold": 0.8,
            "agent.multi_agent.capability_confidence_threshold": 0.55,
            "agent.api_tools.enabled": True,
            "security.operatorMode": "Operator",
            "security.defaultUserRole": "operator",
            "security.enforceRBAC": True,
            "security.pathGuard.enabled": True,
            "security.enableDangerousTools": True,
            "security.requireConfirmationForRisky": False,
            "security.kvkk.strict": True,
            "security.kvkk.redactCloudPrompts": True,
            "security.kvkk.allowCloudFallback": True,
            "tools.requireApproval": [],
            "agent.response_style.mode": "friendly",
            "agent.response_style.friendly": True,
            "agent.response_style.share_manifest_default": False,
            "agent.response_style.share_attachments_default": False,
        },
    }

    def resolve(self) -> RuntimePolicy:
        return RuntimePolicy(
            name=str(elyan_config.get("agent.runtime_policy.preset", "custom") or "custom"),
            flags={
                "agentic_v2": bool(elyan_config.get("agent.flags.agentic_v2", False)),
                "dag_exec": bool(elyan_config.get("agent.flags.dag_exec", False)),
                "strict_taskspec": bool(elyan_config.get("agent.flags.strict_taskspec", False)),
            },
            capability={
                "enabled": bool(elyan_config.get("agent.capability_router.enabled", True)),
                "min_confidence_override": float(
                    elyan_config.get("agent.capability_router.min_confidence_override", 0.5) or 0.5
                ),
            },
            planning={
                "use_llm": bool(elyan_config.get("agent.planning.use_llm", True)),
                "max_subtasks": int(elyan_config.get("agent.planning.max_subtasks", 10) or 10),
            },
            orchestration={
                "multi_agent_enabled": bool(elyan_config.get("agent.multi_agent.enabled", True)),
                "complexity_threshold": float(
                    elyan_config.get("agent.multi_agent.complexity_threshold", 0.9) or 0.9
                ),
                "capability_confidence_threshold": float(
                    elyan_config.get("agent.multi_agent.capability_confidence_threshold", 0.7) or 0.7
                ),
                "team_threshold": float(elyan_config.get("agent.team_mode.threshold", 0.95) or 0.95),
                "max_parallel": int(
                    elyan_config.get(
                        "agent.orchestration.max_parallel",
                        elyan_config.get("agent.team_mode.max_parallel", 4),
                    )
                    or 4
                ),
                "team_max_parallel": int(elyan_config.get("agent.team_mode.max_parallel", 4) or 4),
                "team_timeout_s": int(elyan_config.get("agent.team_mode.timeout_s", 900) or 900),
                "team_max_retries_per_task": int(elyan_config.get("agent.team_mode.max_retries_per_task", 1) or 1),
            },
            api_tools={"enabled": bool(elyan_config.get("agent.api_tools.enabled", True))},
            skills={
                "enabled": [
                    str(x).strip()
                    for x in (elyan_config.get("skills.enabled", []) or [])
                    if str(x).strip()
                ],
                "workflows_enabled": [
                    str(x).strip()
                    for x in (elyan_config.get("skills.workflows.enabled", []) or [])
                    if str(x).strip()
                ],
            },
            tools={
                "allow": [
                    str(x).strip()
                    for x in (elyan_config.get("tools.allow", []) or [])
                    if str(x).strip()
                ],
                "deny": [
                    str(x).strip()
                    for x in (elyan_config.get("tools.deny", []) or [])
                    if str(x).strip()
                ],
                "require_approval": [
                    str(x).strip()
                    for x in (
                        elyan_config.get(
                            "tools.requireApproval",
                            elyan_config.get("tools.require_approval", []),
                        )
                        or []
                    )
                    if str(x).strip()
                ],
            },
            response={
                "friendly": bool(elyan_config.get("agent.response_style.friendly", True)),
                "mode": str(elyan_config.get("agent.response_style.mode", "friendly") or "friendly"),
                "share_manifest_default": bool(elyan_config.get("agent.response_style.share_manifest_default", False)),
                "share_attachments_default": bool(elyan_config.get("agent.response_style.share_attachments_default", False)),
            },
            security={
                "operator_mode": str(elyan_config.get("security.operatorMode", "Confirmed") or "Confirmed"),
                "local_first_models": bool(elyan_config.get("agent.model.local_first", True)),
                "default_user_role": str(elyan_config.get("security.defaultUserRole", "operator") or "operator"),
                "enforce_rbac": bool(elyan_config.get("security.enforceRBAC", True)),
                "path_guard_enabled": bool(elyan_config.get("security.pathGuard.enabled", True)),
                "allowed_roots": self._as_list(
                    elyan_config.get(
                        "security.pathGuard.allowedRoots",
                        [str(Path.home()), "/tmp", "/private", "/var/tmp", "/var/folders", str(Path.home() / ".elyan")],
                    ),
                    [str(Path.home()), "/tmp", "/private", "/var/tmp", "/var/folders", str(Path.home() / ".elyan")],
                ),
                "denied_roots": self._as_list(
                    elyan_config.get("security.pathGuard.deniedRoots", ["/System", "/usr", "/bin", "/sbin", "/etc", "/var/root"]),
                    ["/System", "/usr", "/bin", "/sbin", "/etc", "/var/root"],
                ),
                "dangerous_command_patterns": self._as_list(
                    elyan_config.get(
                        "security.dangerousCommandPatterns",
                        ["rm -rf", "mkfs", "dd if=", "shutdown -h", "reboot", "kill -9 1", ":(){:|:&};:"],
                    ),
                    ["rm -rf", "mkfs", "dd if=", "shutdown -h", "reboot", "kill -9 1", ":(){:|:&};:"],
                ),
                "dangerous_tools_enabled": bool(elyan_config.get("security.enableDangerousTools", True)),
                "require_confirmation_for_risky": bool(elyan_config.get("security.requireConfirmationForRisky", True)),
                "require_evidence_for_dangerous": bool(elyan_config.get("security.requireEvidenceForDangerous", True)),
                "kvkk_strict_mode": bool(elyan_config.get("security.kvkk.strict", True)),
                "redact_cloud_prompts": bool(elyan_config.get("security.kvkk.redactCloudPrompts", True)),
                "allow_cloud_fallback": bool(elyan_config.get("security.kvkk.allowCloudFallback", True)),
            },
        )

    def apply_preset(self, preset: str) -> RuntimePolicy:
        key = str(preset or "").strip().lower()
        conf = self.PRESETS.get(key)
        if not conf:
            return self.resolve()
        for k, v in conf.items():
            elyan_config.set(k, v)
        elyan_config.set("agent.runtime_policy.preset", key)
        return self.resolve()


_runtime_policy_resolver: RuntimePolicyResolver | None = None


def get_runtime_policy_resolver() -> RuntimePolicyResolver:
    global _runtime_policy_resolver
    if _runtime_policy_resolver is None:
        _runtime_policy_resolver = RuntimePolicyResolver()
    return _runtime_policy_resolver


__all__ = ["RuntimePolicy", "RuntimePolicyResolver", "get_runtime_policy_resolver"]
