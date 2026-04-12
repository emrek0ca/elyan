from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentMode(str, Enum):
    CHAT = "chat"
    DIGEST = "digest"
    RESEARCH = "research"
    CODING = "coding"
    AUTOMATION = "automation"


@dataclass(frozen=True, slots=True)
class AgentModePolicy:
    mode: AgentMode
    preferred_model_role: str
    local_first_bias: bool
    allowed_tool_groups: tuple[str, ...]
    delivery_formats: tuple[str, ...]
    allowed_tools: tuple[str, ...] = ()
    blocked_tools: tuple[str, ...] = ()
    allow_unknown_tools: bool = True

    def allows_tool(self, tool_name: str, tool_group: str = "") -> bool:
        normalized_tool = str(tool_name or "").strip().lower()
        normalized_group = str(tool_group or "").strip().lower()
        if not normalized_tool:
            return True
        if normalized_tool in {str(item).strip().lower() for item in self.blocked_tools}:
            return False
        if normalized_tool in {str(item).strip().lower() for item in self.allowed_tools}:
            return True
        if normalized_group and normalized_group in {str(item).strip().lower() for item in self.allowed_tool_groups}:
            return True
        return bool(self.allow_unknown_tools)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "preferred_model_role": self.preferred_model_role,
            "local_first_bias": self.local_first_bias,
            "allowed_tool_groups": list(self.allowed_tool_groups),
            "delivery_formats": list(self.delivery_formats),
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "allow_unknown_tools": self.allow_unknown_tools,
        }


_MODE_POLICIES: dict[str, AgentModePolicy] = {
    AgentMode.CHAT.value: AgentModePolicy(
        mode=AgentMode.CHAT,
        preferred_model_role="inference",
        local_first_bias=True,
        allowed_tool_groups=("fs", "web", "ui", "runtime", "messaging", "automation", "memory", "research", "code"),
        delivery_formats=("text", "mobile"),
        allow_unknown_tools=True,
    ),
    AgentMode.DIGEST.value: AgentModePolicy(
        mode=AgentMode.DIGEST,
        preferred_model_role="planning",
        local_first_bias=True,
        allowed_tool_groups=("web", "messaging", "automation", "memory", "runtime"),
        delivery_formats=("terminal", "mobile", "speech"),
        allowed_tools=("write_file", "create_folder"),
        allow_unknown_tools=False,
    ),
    AgentMode.RESEARCH.value: AgentModePolicy(
        mode=AgentMode.RESEARCH,
        preferred_model_role="research_worker",
        local_first_bias=False,
        allowed_tool_groups=("research", "web", "fs", "memory", "runtime"),
        delivery_formats=("text", "report", "mobile"),
        allowed_tools=("write_file", "create_folder", "research_document_delivery", "advanced_research"),
        blocked_tools=("delete_file",),
        allow_unknown_tools=False,
    ),
    AgentMode.CODING.value: AgentModePolicy(
        mode=AgentMode.CODING,
        preferred_model_role="code_worker",
        local_first_bias=True,
        allowed_tool_groups=("code", "fs", "runtime", "memory", "web"),
        delivery_formats=("text", "patch", "report"),
        allowed_tools=("run_safe_command", "write_file", "create_folder", "list_files", "read_file", "search_files"),
        blocked_tools=("delete_file",),
        allow_unknown_tools=False,
    ),
    AgentMode.AUTOMATION.value: AgentModePolicy(
        mode=AgentMode.AUTOMATION,
        preferred_model_role="planning",
        local_first_bias=True,
        allowed_tool_groups=("automation", "messaging", "memory", "runtime", "web", "fs", "ui"),
        delivery_formats=("text", "mobile"),
        allowed_tools=("write_file", "create_folder", "run_safe_command"),
        allow_unknown_tools=False,
    ),
}


def normalize_agent_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return AgentMode.CHAT.value
    aliases = {
        "assistant": AgentMode.CHAT.value,
        "conversation": AgentMode.CHAT.value,
        "digests": AgentMode.DIGEST.value,
        "briefing": AgentMode.DIGEST.value,
        "brief": AgentMode.DIGEST.value,
        "researcher": AgentMode.RESEARCH.value,
        "deep_research": AgentMode.RESEARCH.value,
        "code": AgentMode.CODING.value,
        "coding": AgentMode.CODING.value,
        "developer": AgentMode.CODING.value,
        "automation": AgentMode.AUTOMATION.value,
        "routine": AgentMode.AUTOMATION.value,
        "scheduler": AgentMode.AUTOMATION.value,
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in _MODE_POLICIES else AgentMode.CHAT.value


def infer_agent_mode(
    *,
    metadata: dict[str, Any] | None = None,
    route_metadata: dict[str, Any] | None = None,
    user_input: str = "",
    action: str = "",
    channel: str = "cli",
) -> str:
    merged: dict[str, Any] = {}
    if isinstance(route_metadata, dict):
        merged.update(route_metadata)
    if isinstance(metadata, dict):
        merged.update(metadata)

    for candidate in (
        merged.get("agent_mode"),
        merged.get("mode"),
        merged.get("command"),
        merged.get("subcommand"),
        merged.get("entrypoint"),
        merged.get("job_type"),
        merged.get("request_kind"),
        action,
    ):
        token = normalize_agent_mode(candidate)
        if candidate and token:
            if token != AgentMode.CHAT.value or str(candidate or "").strip().lower() in _MODE_POLICIES:
                return token

    low = str(user_input or "").strip().lower()
    if any(token in low for token in ("daily report", "günlük özet", "morning digest", "sabah özeti")):
        return AgentMode.DIGEST.value
    if any(token in low for token in ("araştır", "research", "source", "kaynak")):
        return AgentMode.RESEARCH.value
    if any(token in low for token in ("kod", "code", "repo", "test", "patch")):
        return AgentMode.CODING.value
    if any(token in low for token in ("rutin", "schedule", "cron", "automation", "otomasyon")):
        return AgentMode.AUTOMATION.value

    _ = channel
    return AgentMode.CHAT.value


def get_agent_mode_policy(mode: Any) -> AgentModePolicy:
    return _MODE_POLICIES[normalize_agent_mode(mode)]


def build_agent_mode_policy_map() -> dict[str, dict[str, Any]]:
    return {name: policy.to_dict() for name, policy in _MODE_POLICIES.items()}


__all__ = [
    "AgentMode",
    "AgentModePolicy",
    "build_agent_mode_policy_map",
    "get_agent_mode_policy",
    "infer_agent_mode",
    "normalize_agent_mode",
]
