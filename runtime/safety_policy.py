from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.capability_spec import policy_gate_for
from runtime.execution_trust import verify_grant_for_policy


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
    "text_analyze",
    "chart_generate",
    "web_research",
    "image_fetch",
    "file_read",
    "file_search",
    "directory_tree",
    "git_status",
    "git_diff",
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
    "clipboard_read",
    "clipboard_write",
}

DESTRUCTIVE_OR_SENSITIVE_TOOLS = {
    "shell_run",
    "delete_memory",
    "delete_calendar_event",
}

FULL_ACCESS_GRANTED_PERMISSIONS = {
    "allow_shell",
    "allow_computer_control",
    "allow_screen_analysis",
    "allow_system_inspection",
    "allow_browser_control",
    "allow_personal_actions",
    "allow_destructive_tools",
    "allow_sensitive_operator_actions",
}

WRITE_CAPABILITIES = {
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "image_generate",
    "image_edit",
    "file_write",
    "file_patch",
}

# git_guard: yerel repo mutasyonları — onaysız çalışmaz. PUSH/REMOTE burada YOK.
GIT_MUTATION_CAPABILITIES = {
    "git_commit",
    "git_branch",
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


# ── Gerçek OS izni tek doğruluk kaynağıdır ────────────────────────────────────
# Apple-kalite: kullanıcı macOS Ekran Kaydı / Erişilebilirlik iznini verince
# yetenek ÇALIŞMALI — ikinci bir Elyan-içi "tam yetki" toggle'ı istenmez. Eski
# davranış yalnız Elyan flag'lerine bakıyordu; kullanıcı gerçek izni verse de
# "Tam yetki kapalı" ile bloklanıyordu (canlı arıza). Salt-okunur OS-destekli
# yetenekler için gerçek TCC iznini canlı prob'la kontrol edip otomatik geçeriz.

# Yetenek → gereken macOS OS izni.
_OS_BACKED_READ_CAPABILITIES = {
    "analyze_screen": "screenRecording",
    "desktop_operator.observe_screen": "screenRecording",
    "desktop_operator.locate": "screenRecording",
    "desktop_os.active_window": "accessibility",
    "desktop_os.processes": "accessibility",
}

_OS_PERMISSION_MESSAGES = {
    "screenRecording": (
        "Ekranı görebilmem için macOS Ekran Kaydı iznini açman yeterli: "
        "Sistem Ayarları > Gizlilik ve Güvenlik > Ekran ve Sistem Sesi Kaydı > "
        "'elyan Screen Helper'ı aç. Zaten açıksa Elyan'ı yeniden başlat."
    ),
    "accessibility": (
        "Bunun için macOS Erişilebilirlik iznini açman yeterli: "
        "Sistem Ayarları > Gizlilik ve Güvenlik > Erişilebilirlik > "
        "'elyan Screen Helper' (veya Elyan'ı çalıştıran uygulama) izinli olmalı."
    ),
}

import time as _time  # noqa: E402

_os_perm_cache: dict[str, tuple[bool | None, float]] = {}
_OS_PERM_TTL_SECONDS = 15.0


def _probe_os_permission(requirement: str) -> bool | None:
    """Gerçek macOS TCC iznini canlı prob'lar (kısa TTL cache). darwin dışı ya da
    prob edilemezse None (bilinmiyor)."""
    import sys as _sys

    if _sys.platform != "darwin":
        return None
    now = _time.monotonic()
    cached = _os_perm_cache.get(requirement)
    if cached is not None and (now - cached[1]) < _OS_PERM_TTL_SECONDS:
        return cached[0]
    value: bool | None = None
    try:
        from actions.desktop_os import _macos_permission_value

        if requirement == "screenRecording":
            value = _macos_permission_value(
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
                "CGPreflightScreenCaptureAccess",
            )
        elif requirement == "accessibility":
            value = _macos_permission_value(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
                "AXIsProcessTrusted",
            )
    except Exception:
        value = None
    _os_perm_cache[requirement] = (value, now)
    return value


def _os_permission_allows(name: str) -> bool:
    """Salt-okunur OS-destekli gözlem yetenekleri policy'de GEÇER; gerçek izni
    OS/yardımcı YÜRÜTMEDE uygular.

    Neden probe'a güvenmiyoruz: ekran yakalama ayrı 'elyan Screen Helper'
    binary'sine delege edilir; daemon python'unun kendi CGPreflightScreenCapture
    Access'i (helper izinli olsa bile) False dönebilir (yanıltıcı negatif). İç
    'tam yetki' kapısı bu yüzden kullanıcı gerçek izni verse de bloklu yordu.
    Politika izin verir; helper izinliyse çalışır, değilse capability KENDİ
    doğru mesajını döndürür (PERMISSION_REQUIRED → replan YOK → okunaklı)."""
    return name in _OS_BACKED_READ_CAPABILITIES


def _os_requirement_message(name: str) -> str:
    requirement = _OS_BACKED_READ_CAPABILITIES.get(name, "")
    return _OS_PERMISSION_MESSAGES.get(requirement, "")


def _full_access_enabled(state: dict[str, Any]) -> bool:
    runtime = state.get("runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    access = runtime.get("access", {})
    access = access if isinstance(access, dict) else {}
    session = access.get("fullAccessSession", {})
    session = session if isinstance(session, dict) else {}
    return _truthy(session.get("enabled", False))


def _dangerous_area_enabled(state: dict[str, Any]) -> bool:
    return _full_access_enabled(state)


def _permission_enabled(state: dict[str, Any], key: str) -> bool:
    permissions = _permissions(state)
    if key in FULL_ACCESS_GRANTED_PERMISSIONS and _full_access_enabled(state):
        return True
    return False


def _permission_block(state: dict[str, Any], key: str, disabled_message: str, master_message: str) -> PolicyDecision:
    if key in FULL_ACCESS_GRANTED_PERMISSIONS and _full_access_enabled(state):
        return PolicyDecision(True)
    return PolicyDecision(False, "PERMISSION_REQUIRED", master_message or disabled_message)


def evaluate_tool(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> PolicyDecision:
    name = str(tool_name or "").strip()
    if not name:
        return PolicyDecision(False, "UNKNOWN_CAPABILITY", "Bilinmeyen araç.")

    grant_error = verify_grant_for_policy(name, args, state)
    if grant_error is not None:
        return PolicyDecision(False, grant_error.code, "Görev yetkisi bu adıma uymuyor; işlem durduruldu.")

    if name == "shell_run":
        mode = str(args.get("mode", "") or "").strip().lower()
        risk_override = str(args.get("riskOverride", "") or args.get("risk_override", "") or "").strip().lower()
        if mode == "read_only" or _truthy(args.get("_readOnlyHint", False)):
            return PolicyDecision(True)
        if risk_override in {"critical", "credential", "payment", "irreversible_delete", "upload", "share"}:
            if not _permission_enabled(state, "allow_destructive_tools") or not _truthy(args.get("_confirmed", False)):
                return PolicyDecision(
                    False,
                    "PERMISSION_REQUIRED",
                    "Kilit eylem için ayrıca açık onay gerekiyor.",
                )
            return PolicyDecision(True)
        shell_gate = _permission_block(
            state,
            "allow_shell",
            "Gelişmiş komut izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Terminal komutları için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if not shell_gate.allowed:
            return shell_gate
        if mode == "full_access" and _full_access_enabled(state):
            return PolicyDecision(True)
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

    if name == "backend.integrations.disconnect":
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Uygulama bağlantısını kaldırmak için açık onay gerekiyor.",
        )

    if name in {"delete_memory", "delete_calendar_event"}:
        destructive_gate = _permission_block(
            state,
            "allow_destructive_tools",
            "Silme ve geri alınamaz işlem izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Silme ve geri alınamaz işlemler için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if not destructive_gate.allowed:
            return destructive_gate
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Bu geri alınamaz işlem için açık onay gerekiyor.",
        )

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

    if name in GIT_MUTATION_CAPABILITIES:
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Git deposunu değiştirmek için açık onay gerekiyor (push yapılmaz).",
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

    # Tek Spec mimarisi: göç edilen yetenekler kapısını spec'ten alır —
    # kural burada değil, yeteneğin tek kaydında yaşar.
    spec_gate = policy_gate_for(name)
    if spec_gate == "open":
        return PolicyDecision(True)
    if spec_gate == "confirm":
        if _truthy(args.get("_confirmed", False)):
            return PolicyDecision(True)
        return PolicyDecision(
            False,
            "PERMISSION_REQUIRED",
            "Bu işlem için açık onay gerekiyor.",
        )
    if spec_gate.startswith("permission:"):
        permission_key = spec_gate.split(":", 1)[1]
        gate = _permission_block(
            state,
            permission_key,
            "Bu yetenek için gizlilik izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            "Tam yetki kapalı. Bu işlem için önce Ayarlar > Gizlilik bölümünden tam yetkiyi aç.",
        )
        if gate.allowed:
            return PolicyDecision(True)
        return gate

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
        # Apple-kalite: gerçek OS izni verildiyse çalış (ikinci toggle isteme).
        if _os_permission_allows(name):
            return PolicyDecision(True)
        system_gate = _permission_block(
            state,
            "allow_system_inspection",
            "Sistem görünürlüğü izni kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.",
            _os_requirement_message(name),
        )
        if system_gate.allowed:
            return PolicyDecision(True)
        return system_gate

    if name == "analyze_screen":
        if _os_permission_allows(name):
            return PolicyDecision(True)
        screen_gate = _permission_block(
            state,
            "allow_screen_analysis",
            _os_requirement_message(name),
            _os_requirement_message(name),
        )
        if screen_gate.allowed:
            return PolicyDecision(True)
        return screen_gate

    if name in {"desktop_operator.observe_screen", "desktop_operator.locate"}:
        if _os_permission_allows(name):
            return PolicyDecision(True)
        screen_gate = _permission_block(
            state,
            "allow_screen_analysis",
            _os_requirement_message(name),
            _os_requirement_message(name),
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
        if risky_hint and _full_access_enabled(state):
            if not _truthy(args.get("_confirmed", False)):
                return PolicyDecision(
                    False,
                    "PERMISSION_REQUIRED",
                    "Kilit operator eylemi için açık onay gerekiyor.",
                )
            return PolicyDecision(True)
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
