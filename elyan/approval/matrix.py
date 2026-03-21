from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalLevel(IntEnum):
    NONE = 0
    CONFIRM = 1
    SCREEN = 2
    TWO_FA = 3
    MANUAL = 4


_DANGEROUS_COMMAND_MARKERS = (
    "rm -rf",
    "mkfs",
    "dd if=",
    "chmod 777",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "kill -9 1",
    ":(){",
)

_DANGEROUS_TEXT_MARKERS = (
    "delete ",
    "delete file",
    "remove ",
    "remove file",
    "send email",
    "send mail",
    "post ",
    "publish ",
    "share ",
    "shutdown",
    "restart",
    "sleep",
    "lock screen",
    "format",
    "wipe",
    "destroy",
)

_FILE_SCREEN_ACTIONS = {
    "delete_file",
    "delete_folder",
    "remove_file",
    "remove_folder",
}

_FILE_CONFIRM_ACTIONS = {
    "move_file",
    "copy_file",
    "rename_file",
}

_SOCIAL_CONFIRM_ACTIONS = {
    "post",
    "publish",
    "post_instagram",
    "post_social",
    "share_post",
}

_MAIL_TWO_FA_ACTIONS = {
    "send_email",
    "mail_send",
    "gmail_send",
    "send_mail",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _dangerous_command_level(command: str) -> ApprovalLevel:
    text = _clean_text(command)
    if not text:
        return ApprovalLevel.NONE
    if any(marker in text for marker in _DANGEROUS_COMMAND_MARKERS):
        return ApprovalLevel.SCREEN
    if "sudo " in text or text.startswith("sudo"):
        return ApprovalLevel.TWO_FA
    return ApprovalLevel.NONE


def _descriptive_text_level(text: str) -> ApprovalLevel:
    lowered = _clean_text(text)
    if not lowered:
        return ApprovalLevel.NONE
    if any(marker in lowered for marker in ("shutdown", "restart", "format", "wipe", "destroy")):
        return ApprovalLevel.SCREEN
    if any(marker in lowered for marker in ("send email", "send mail", "mail gönder", "mail gonder")):
        return ApprovalLevel.TWO_FA
    if any(marker in lowered for marker in ("delete file", "delete ", "remove file", "remove ")):
        return ApprovalLevel.SCREEN
    if any(marker in lowered for marker in ("post ", "publish ", "share ")):
        return ApprovalLevel.CONFIRM
    return ApprovalLevel.NONE


class ApprovalMatrix(BaseModel):
    skill_name: str = ""
    integration_type: str = ""
    destructive: bool = False
    required_level: ApprovalLevel = ApprovalLevel.NONE
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @staticmethod
    def get_for_skill(skill_name: str, action: dict[str, Any] | None) -> "ApprovalMatrix":
        payload = dict(action or {})
        resolved_skill = _clean_text(skill_name or payload.get("skill_name") or payload.get("integration_type") or payload.get("skill") or "")
        action_type = _clean_text(payload.get("type") or payload.get("action") or payload.get("name") or resolved_skill)
        description = _clean_text(payload.get("description") or payload.get("summary") or payload.get("command") or payload.get("instruction"))
        integration_type = _clean_text(payload.get("integration_type") or payload.get("skill_type") or resolved_skill)
        scopes = _as_list(payload.get("scopes") or payload.get("required_scopes") or [])

        level = ApprovalLevel.NONE
        destructive = bool(payload.get("destructive", False))

        if action_type in {"shutdown_system", "restart_system"}:
            level = ApprovalLevel.SCREEN
            destructive = True
        elif action_type in {"sleep_system", "lock_screen"}:
            level = ApprovalLevel.CONFIRM
            destructive = True
        elif action_type == "kill_process":
            level = ApprovalLevel.SCREEN
            destructive = True
        elif action_type in _MAIL_TWO_FA_ACTIONS or integration_type in {"email", "mail", "gmail"} or resolved_skill in {"email", "gmail", "mail"}:
            level = ApprovalLevel.TWO_FA
            destructive = True
        elif action_type in _FILE_SCREEN_ACTIONS:
            level = ApprovalLevel.SCREEN
            destructive = True
        elif action_type in _FILE_CONFIRM_ACTIONS:
            level = ApprovalLevel.CONFIRM
            destructive = True
        elif action_type in _SOCIAL_CONFIRM_ACTIONS or integration_type in {"social", "instagram"} or resolved_skill in {"instagram", "social"}:
            level = ApprovalLevel.CONFIRM
            destructive = True
        elif action_type in {"run_safe_command", "run_command", "execute_command", "execute_shell_command"}:
            level = _dangerous_command_level(description)
            destructive = level >= ApprovalLevel.SCREEN
        elif action_type in {"instruction", "run_screen_operator", "computer_use", "inspect_and_control"}:
            level = max(level, _descriptive_text_level(description))
            destructive = destructive or level >= ApprovalLevel.SCREEN

        if bool(payload.get("requires_2fa")):
            level = max(level, ApprovalLevel.TWO_FA)
        if bool(payload.get("requires_screen")):
            level = max(level, ApprovalLevel.SCREEN)
        if bool(payload.get("manual_only")):
            level = ApprovalLevel.MANUAL
        if bool(payload.get("approval_required")):
            level = max(level, ApprovalLevel.CONFIRM)
        if bool(payload.get("destructive")):
            level = max(level, ApprovalLevel.SCREEN)
            destructive = True

        explicit = payload.get("approval_level")
        if explicit is not None and str(explicit).strip() != "":
            try:
                level = max(level, ApprovalLevel(int(explicit)))
            except Exception:
                pass

        metadata = {
            "action_type": action_type,
            "description": description,
            "integration_type": integration_type,
        }
        return ApprovalMatrix(
            skill_name=resolved_skill or skill_name,
            integration_type=integration_type,
            destructive=destructive or level >= ApprovalLevel.SCREEN,
            required_level=level,
            scopes=scopes,
            metadata=metadata,
        )


def get_approval_matrix(skill_name: str, action: dict[str, Any] | None = None) -> ApprovalMatrix:
    return ApprovalMatrix.get_for_skill(skill_name, action)
