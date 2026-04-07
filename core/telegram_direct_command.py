from __future__ import annotations

from typing import Any


def normalize_telegram_instruction(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "", ""

    if not raw.startswith("/"):
        return raw, ""

    command_part, _, remainder = raw.partition(" ")
    command_name = command_part[1:].split("@", 1)[0].strip().lower()
    normalized = " ".join(part for part in (command_name, remainder.strip()) if part).strip()
    return normalized, command_name


def build_telegram_metadata(
    *,
    user_id: str | int,
    chat_id: str | int,
    user_name: str = "",
    source: str = "telegram_text",
    raw_text: str = "",
    normalized_text: str = "",
    command_name: str = "",
    message_id: str | int = "",
    chat_type: str = "",
    is_group: bool = False,
    mentioned: bool = False,
    is_inline_reply: bool = False,
    reply_to_message_id: str | int = "",
    has_attachments: bool = False,
    is_voice: bool = False,
    bot_username: str = "",
) -> dict[str, Any]:
    command_name = str(command_name or "").strip().lower()
    is_command = bool(command_name)
    return {
        "channel_type": "telegram",
        "channel_id": str(chat_id or ""),
        "telegram_user_id": str(user_id or ""),
        "telegram_chat_id": str(chat_id or ""),
        "telegram_user_name": str(user_name or ""),
        "telegram_message_id": str(message_id or ""),
        "telegram_command": command_name,
        "telegram_source": str(source or "telegram_text"),
        "telegram_raw_text": str(raw_text or ""),
        "telegram_normalized_text": str(normalized_text or ""),
        "telegram_chat_type": str(chat_type or ""),
        "is_group": bool(is_group),
        "mentioned": bool(mentioned),
        "is_inline_reply": bool(is_inline_reply),
        "reply_to_message_id": str(reply_to_message_id or ""),
        "has_attachments": bool(has_attachments),
        "is_voice": bool(is_voice),
        "bot_username": str(bot_username or ""),
        "request_kind": "telegram_command" if is_command else "chat",
        "request_class": "direct_action" if is_command else "chat",
        "execution_path": "fast" if is_command else "chat",
    }


def is_local_telegram_command(command_name: str) -> bool:
    return str(command_name or "").strip().lower() in {"start", "status", "help"}
