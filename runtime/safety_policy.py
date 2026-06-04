from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str = ""
    message: str = ""


KNOWN_SAFE_TOOLS = {
    "open_app",
    "close_app",
    "sys_info",
    "get_weather",
    "get_calendar_events",
    "get_reminders",
    "get_youtube_channel_report",
    "save_memory",
    "document_read",
    "ocr_read",
    "image_read",
    "data_analyze",
    "chart_generate",
    "web_research",
    "email_draft",
    "math_solve",
    "latex_parse",
    "quantum_model_problem",
    "quantum_run_experiment",
    "quantum_compare_classical",
    "quantum_generate_report",
    "retrieve_context",
    "speech_to_text",
    "text_to_speech",
    "desktop_os.status",
    "desktop_os.permissions",
}

DESTRUCTIVE_OR_SENSITIVE_TOOLS = {
    "shell_run",
    "delete_memory",
    "delete_calendar_event",
}

WRITE_CAPABILITIES = {
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "image_generate",
}

PERSONAL_ACTION_CAPABILITIES = {
    "add_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _permissions(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("permissions", {})
    return raw if isinstance(raw, dict) else {}


def _dangerous_area_enabled(state: dict[str, Any]) -> bool:
    account = state.get("account", {})
    if not isinstance(account, dict):
        return False
    return _truthy(account.get("dangerousAreaEnabled", False))


def _permission_enabled(state: dict[str, Any], key: str) -> bool:
    permissions = _permissions(state)
    return _dangerous_area_enabled(state) and _truthy(permissions.get(key, False))


def evaluate_tool(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> PolicyDecision:
    name = str(tool_name or "").strip()
    if not name:
        return PolicyDecision(False, "UNKNOWN_CAPABILITY", "Bilinmeyen araç.")

    if name == "shell_run":
        if not _permission_enabled(state, "allow_shell"):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Terminal komutu çalıştırmak için güvenlik izni gerekiyor.",
            )
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Terminal komutu çalıştırmak için açık onay gerekiyor.",
        )

    if name == "email_send":
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "E-posta göndermek için açık onay gerekiyor.",
        )

    if name in {"delete_memory", "delete_calendar_event"}:
        if _permission_enabled(state, "allow_destructive_tools"):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Bu işlem silme/değişiklik izni gerektiriyor.",
        )

    if name == "send_whatsapp_message" and _truthy(args.get("send_now", False)):
        if not _permission_enabled(state, "allow_destructive_tools"):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Mesaj göndermek için açık izin gerekiyor.",
            )

    if name in PERSONAL_ACTION_CAPABILITIES:
        if not _permission_enabled(state, "allow_personal_actions"):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Takvim, hatırlatıcı ve mesaj işlemleri için açık izin gerekiyor.",
            )
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Bu kişisel işlemi çalıştırmak için açık onay gerekiyor.",
        )

    if name in WRITE_CAPABILITIES:
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Dosya yazmak için açık onay gerekiyor.",
        )

    if name == "speech_capture":
        if _truthy(args.get("_uiGesture", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Mikrofon kaydı yalnız doğrudan kullanıcı hareketiyle başlatılabilir.",
        )

    if name == "mcp_call_tool":
        if _truthy(args.get("_readOnlyHint", False)) or _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Bu MCP aracı için açık onay gerekiyor.",
        )

    if name in {"browser_control", "play_media"}:
        if _permission_enabled(state, "allow_browser_control"):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Tarayıcı veya medya kontrolü için açık izin gerekiyor.",
        )

    if name in {"desktop_os.processes", "desktop_os.active_window"}:
        if _permission_enabled(state, "allow_system_inspection"):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Sistem proses ve pencere görünürlüğü için açık izin gerekiyor.",
        )

    if name == "analyze_screen":
        if _permission_enabled(state, "allow_screen_analysis"):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Ekran analizi özel ekran görüntüsünü bulut vision yoluna gönderebilir. Çalıştırmak için açık izin gerekiyor.",
        )

    if name in KNOWN_SAFE_TOOLS:
        return PolicyDecision(True)

    if name in DESTRUCTIVE_OR_SENSITIVE_TOOLS:
        return PolicyDecision(False, "PERMISSION_REQUIRED", "Bu araç izin gerektiriyor.")

    return PolicyDecision(False, "UNKNOWN_CAPABILITY", f"Bilinmeyen araç: {name}")
