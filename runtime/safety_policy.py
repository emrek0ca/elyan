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
    "desktop_os.open_permission_settings",
    "desktop_operator.observe_screen",
    "desktop_operator.locate",
    "desktop_operator.focus_window",
    "desktop_operator.cancel",
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
    "canvas_write",
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


def _permission_block(state: dict[str, Any], key: str, disabled_message: str, master_message: str) -> PolicyDecision:
    if not _dangerous_area_enabled(state):
        return PolicyDecision(False, "PERMISSION_REQUIRED", master_message)
    if not _permission_enabled(state, key):
        return PolicyDecision(False, "PERMISSION_REQUIRED", disabled_message)
    return PolicyDecision(True)


def evaluate_tool(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> PolicyDecision:
    name = str(tool_name or "").strip()
    if not name:
        return PolicyDecision(False, "UNKNOWN_CAPABILITY", "Bilinmeyen araç.")

    if name == "shell_run":
        shell_gate = _permission_block(
            state,
            "allow_shell",
            "Gelişmiş komut izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Terminal komutları için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if not shell_gate.allowed:
            return shell_gate
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
        destructive_gate = _permission_block(
            state,
            "allow_destructive_tools",
            "Silme ve geri alınamaz işlem izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Silme ve geri alınamaz işlemler için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if destructive_gate.allowed:
            return PolicyDecision(True)
        return destructive_gate

    if name == "send_whatsapp_message" and _truthy(args.get("send_now", False)):
        if not _permission_enabled(state, "allow_destructive_tools"):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Mesaj göndermek için açık izin gerekiyor.",
            )

    if name in PERSONAL_ACTION_CAPABILITIES:
        personal_gate = _permission_block(
            state,
            "allow_personal_actions",
            "Takvim, hatırlatıcı ve mesaj işlemleri izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Kişisel işlemler için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if not personal_gate.allowed:
            return personal_gate
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
        browser_gate = _permission_block(
            state,
            "allow_browser_control",
            "Tarayıcı ve medya erişimi kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Tarayıcı ve medya işlemleri için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if browser_gate.allowed:
            return PolicyDecision(True)
        return browser_gate

    if name in {"desktop_os.processes", "desktop_os.active_window"}:
        system_gate = _permission_block(
            state,
            "allow_system_inspection",
            "Sistem görünürlüğü izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Sistem görünürlüğü için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if system_gate.allowed:
            return PolicyDecision(True)
        return system_gate

    if name == "analyze_screen":
        screen_gate = _permission_block(
            state,
            "allow_screen_analysis",
            "Ekran okuma izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Ekran analizi için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if screen_gate.allowed:
            return PolicyDecision(True)
        return screen_gate

    if name in {"desktop_operator.observe_screen", "desktop_operator.locate"}:
        screen_gate = _permission_block(
            state,
            "allow_screen_analysis",
            "Visual operator ekran gözlemi kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Visual operator ekran gözlemi için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if screen_gate.allowed:
            return PolicyDecision(True)
        return screen_gate

    if name in {"desktop_operator.focus_window", "desktop_operator.execute_action", "desktop_operator.run"}:
        control_gate = _permission_block(
            state,
            "allow_computer_control",
            "Bilgisayar kontrolü kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Bilgisayar kontrolü için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if not control_gate.allowed:
            return control_gate

        risky_text = " ".join(
            str(args.get(key, "") or "")
            for key in ("actionType", "action", "targetText", "target_text", "text", "goal")
        ).lower()
        risky_hint = _truthy(args.get("_riskyAction", False)) or any(
            token in risky_text
            for token in ("submit", "apply", "pay", "delete", "remove", "send", "install", "upload", "run command")
        )
        if risky_hint and not _permission_enabled(state, "allow_sensitive_operator_actions"):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Riskli operator aksiyonları kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            )
        if risky_hint and not _truthy(args.get("_confirmed", False)):
            return PolicyDecision(
                False,
                "PERMISSION_REQUIRED",
                "Riskli operator aksiyonu için açık onay gerekiyor.",
            )
        return PolicyDecision(True)

    if name == "desktop_operator.cancel":
        return PolicyDecision(True)

    if name in KNOWN_SAFE_TOOLS:
        return PolicyDecision(True)

    if name in DESTRUCTIVE_OR_SENSITIVE_TOOLS:
        return PolicyDecision(False, "PERMISSION_REQUIRED", "Bu araç izin gerektiriyor.")

    return PolicyDecision(False, "UNKNOWN_CAPABILITY", f"Bilinmeyen araç: {name}")
