from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import os
import shutil
import sys
from typing import Any, Callable

from runtime.safety_policy import evaluate_tool


@dataclass(frozen=True)
class _AdapterSpec:
    module: str
    attribute: str


class CapabilityLoadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SafeCapabilityError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CapabilityMetadata:
    name: str
    category: str
    side_effect: bool
    required_permissions: tuple[str, ...]
    permission_class: str
    supported_platforms: tuple[str, ...]
    dependency_keys: tuple[str, ...]
    timeout_seconds: int
    verification_mode: str
    preferred_model_class: str
    retryable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "sideEffect": self.side_effect,
            "requiredPermissions": list(self.required_permissions),
            "permissionClass": self.permission_class,
            "supportedPlatforms": list(self.supported_platforms),
            "dependencyKeys": list(self.dependency_keys),
            "timeoutSeconds": self.timeout_seconds,
            "verificationMode": self.verification_mode,
            "preferredModelClass": self.preferred_model_class,
            "retryable": self.retryable,
        }


def _normalize_capability_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(".", "_").replace(" ", "_")


_CAPABILITY_SYSTEM_PERMISSION_KEYS: dict[str, str] = {
    "browser_control": "accessibility",
    "play_media": "accessibility",
    "analyze_screen": "screenRecording",
    "desktop_os.active_window": "accessibility",
    "desktop_operator.observe_screen": "screenRecording",
    "desktop_operator.locate": "screenRecording",
    "desktop_operator.focus_window": "accessibility",
    "desktop_operator.execute_action": "accessibility",
    "desktop_operator.run": "accessibility",
    "desktop_operator.cancel": "accessibility",
}


def _system_permission_message(permission_key: str) -> str:
    normalized = str(permission_key or "").strip().lower()
    if normalized == "screenrecording":
        return "macOS ekran kaydı izni kapalı."
    if normalized == "accessibility":
        return "macOS erişilebilirlik izni kapalı."
    if normalized == "automation":
        return "macOS otomasyon izni kapalı."
    if normalized == "inputmonitoring":
        return "macOS giriş izleme izni kapalı."
    return "macOS sistem izni gerekiyor."


def _system_permission_status_for_capability(tool_name: str) -> str:
    permission_key = _CAPABILITY_SYSTEM_PERMISSION_KEYS.get(str(tool_name or "").strip(), "")
    if not permission_key:
        return ""
    try:
        desktop_os = import_module("actions.desktop_os")
        payload = desktop_os.desktop_os_permissions()
    except Exception:
        return ""
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    permissions = result.get("permissions", {})
    permissions = permissions if isinstance(permissions, dict) else {}
    state = permissions.get(permission_key, {})
    state = state if isinstance(state, dict) else {}
    return str(state.get("status", "") or "").strip().lower()


def _system_permission_detail_for_capability(tool_name: str, *, allow_probe: bool = False) -> dict[str, Any]:
    permission_key = _CAPABILITY_SYSTEM_PERMISSION_KEYS.get(str(tool_name or "").strip(), "")
    if not permission_key:
        return {}
    if not allow_probe:
        return {
            "systemPermissionKey": permission_key,
            "osPermissionStatus": "",
            "systemPermissionRequired": False,
        }
    try:
        desktop_os = import_module("actions.desktop_os")
        payload = desktop_os.desktop_os_permissions()
    except Exception:
        return {
            "systemPermissionKey": permission_key,
            "osPermissionStatus": "",
        }
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    permissions = result.get("permissions", {})
    permissions = permissions if isinstance(permissions, dict) else {}
    state = permissions.get(permission_key, {})
    state = state if isinstance(state, dict) else {}
    status = str(state.get("status", "") or "").strip().lower()
    return {
        "systemPermissionKey": permission_key,
        "osPermissionStatus": status,
        "systemPermissionRequired": bool(state.get("required", False)),
    }


def _tool_decl(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "description": description,
        "parameters": {
            "type": "OBJECT",
            "properties": properties,
        },
    }
    if required:
        payload["parameters"]["required"] = required
    return payload


TOOL_DECLARATIONS: list[dict[str, Any]] = [
    _tool_decl("open_app", "Uygulama açar.", {"app_name": {"type": "STRING"}}, ["app_name"]),
    _tool_decl("close_app", "Uygulama kapatır.", {"app_name": {"type": "STRING"}}, ["app_name"]),
    _tool_decl(
        "sys_info",
        "Sistem bilgisi alır: pil, CPU, RAM, disk, saat, tarih, ağ.",
        {"query": {"type": "STRING"}},
        ["query"],
    ),
    _tool_decl("get_weather", "Anlık hava durumunu özetler.", {"location": {"type": "STRING"}}),
    _tool_decl(
        "get_calendar_events",
        "Apple Calendar takvimini okur.",
        {"query": {"type": "STRING"}, "limit": {"type": "NUMBER"}},
        ["query"],
    ),
    _tool_decl(
        "add_calendar_event",
        "Apple Calendar takvimine yeni etkinlik ekler.",
        {
            "title": {"type": "STRING"},
            "start_iso": {"type": "STRING"},
            "end_iso": {"type": "STRING"},
            "location": {"type": "STRING"},
            "notes": {"type": "STRING"},
            "calendar_name": {"type": "STRING"},
            "all_day": {"type": "BOOLEAN"},
        },
        ["title", "start_iso"],
    ),
    _tool_decl(
        "delete_calendar_event",
        "Apple Calendar takviminden etkinlik siler.",
        {
            "title": {"type": "STRING"},
            "start_iso": {"type": "STRING"},
            "calendar_name": {"type": "STRING"},
            "delete_all_matches": {"type": "BOOLEAN"},
        },
        ["title"],
    ),
    _tool_decl(
        "get_reminders",
        "Apple Reminders listesini okur.",
        {"query": {"type": "STRING"}, "limit": {"type": "NUMBER"}, "list_name": {"type": "STRING"}},
        ["query"],
    ),
    _tool_decl(
        "add_reminder",
        "Apple Reminders'a yeni öğe ekler.",
        {
            "title": {"type": "STRING"},
            "due_iso": {"type": "STRING"},
            "notes": {"type": "STRING"},
            "list_name": {"type": "STRING"},
            "priority": {"type": "STRING"},
            "all_day": {"type": "BOOLEAN"},
        },
        ["title"],
    ),
    _tool_decl(
        "browser_control",
        "Tarayıcıda URL açar, web araması yapar veya YouTube açar.",
        {"action": {"type": "STRING"}, "url": {"type": "STRING"}, "query": {"type": "STRING"}},
        ["action"],
    ),
    _tool_decl(
        "web_research",
        "Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
        {
            "query": {"type": "STRING"},
            "max_results": {"type": "NUMBER"},
            "language_hint": {"type": "STRING"},
        },
        ["query"],
    ),
    _tool_decl(
        "shell_run",
        "Yerel terminal komutu çalıştırır.",
        {
            "command": {"type": "STRING"},
            "mode": {"type": "STRING"},
            "timeout": {"type": "NUMBER"},
            "use_shell": {"type": "BOOLEAN"},
            "working_dir": {"type": "STRING"},
            "riskOverride": {"type": "STRING"},
        },
        ["command"],
    ),
    _tool_decl(
        "play_media",
        "YouTube, Spotify veya Music ile medya oynatır.",
        {"query": {"type": "STRING"}, "provider": {"type": "STRING"}, "autoplay": {"type": "BOOLEAN"}},
        ["query"],
    ),
    _tool_decl(
        "analyze_screen",
        "Aktif ekranı analiz eder.",
        {"query": {"type": "STRING"}, "target": {"type": "STRING"}},
        ["query"],
    ),
    _tool_decl(
        "desktop_operator.observe_screen",
        "Aktif pencereyi structured ekran gözlemine çevirir.",
        {
            "query": {"type": "STRING"},
            "target": {"type": "STRING"},
            "preserveScreenshot": {"type": "BOOLEAN"},
        },
    ),
    _tool_decl(
        "desktop_operator.locate",
        "Metin veya öğe tipine göre ekrandaki hedef öğeyi bulur.",
        {
            "text": {"type": "STRING"},
            "elementType": {"type": "STRING"},
        },
    ),
    _tool_decl(
        "desktop_operator.focus_window",
        "Bir masaüstü uygulamasını öne alır.",
        {"appName": {"type": "STRING"}, "bundleId": {"type": "STRING"}},
    ),
    _tool_decl(
        "desktop_operator.execute_action",
        "Visual desktop operator ile güvenli bir UI aksiyonu çalıştırır.",
        {
            "actionType": {"type": "STRING"},
            "targetText": {"type": "STRING"},
            "elementType": {"type": "STRING"},
            "bbox": {"type": "OBJECT"},
            "text": {"type": "STRING"},
            "keys": {"type": "ARRAY"},
            "delta": {"type": "NUMBER"},
            "duration": {"type": "NUMBER"},
            "appName": {"type": "STRING"},
        },
        ["actionType"],
    ),
    _tool_decl(
        "desktop_operator.run",
        "Observe -> locate -> execute -> verify döngüsüyle görev tabanlı operator akışı çalıştırır.",
        {
            "goal": {"type": "STRING"},
            "action": {"type": "STRING"},
            "targetText": {"type": "STRING"},
            "elementType": {"type": "STRING"},
            "text": {"type": "STRING"},
            "appName": {"type": "STRING"},
            "steps": {"type": "ARRAY"},
        },
    ),
    _tool_decl(
        "desktop_operator.cancel",
        "Aktif visual desktop operator çalışmasını güvenli şekilde durdurur.",
        {
            "runId": {"type": "STRING"},
            "reason": {"type": "STRING"},
            "source": {"type": "STRING"},
        },
    ),
    _tool_decl(
        "get_youtube_channel_report",
        "YouTube kanal istatistiklerini ve son video performansını raporlar.",
        {"query": {"type": "STRING"}, "handle": {"type": "STRING"}, "video_limit": {"type": "NUMBER"}},
    ),
    _tool_decl(
        "send_whatsapp_message",
        "WhatsApp Desktop/Web üzerinden mesaj hazırlar veya gönderir.",
        {
            "recipient_name": {"type": "STRING"},
            "phone_number": {"type": "STRING"},
            "message": {"type": "STRING"},
            "app_target": {"type": "STRING"},
            "send_now": {"type": "BOOLEAN"},
        },
        ["message"],
    ),
    _tool_decl(
        "save_whatsapp_contact",
        "WhatsApp kişisini kalıcı kaydeder.",
        {"display_name": {"type": "STRING"}, "phone_number": {"type": "STRING"}, "aliases": {"type": "STRING"}},
        ["display_name", "phone_number"],
    ),
    _tool_decl(
        "email_draft",
        "E-posta taslağı hazırlar.",
        {
            "to": {"type": "ARRAY"},
            "subject": {"type": "STRING"},
            "topic": {"type": "STRING"},
            "prompt": {"type": "STRING"},
            "tone": {"type": "STRING"},
        },
        ["to"],
    ),
    _tool_decl(
        "email_send",
        "Onaylı e-postayı gönderir.",
        {
            "to": {"type": "ARRAY"},
            "subject": {"type": "STRING"},
            "body": {"type": "STRING"},
            "connectionId": {"type": "STRING"},
            "cc": {"type": "ARRAY"},
            "bcc": {"type": "ARRAY"},
            "replyTo": {"type": "STRING"},
        },
        ["to", "subject", "body"],
    ),
    _tool_decl(
        "document_read",
        "Belge veya dosya içeriğini güvenli şekilde okur.",
        {
            "path": {"type": "STRING"},
            "text": {"type": "STRING"},
            "mode": {"type": "STRING"},
        },
        ["path"],
    ),
    _tool_decl(
        "ocr_read",
        "Görsel veya PDF sayfasındaki metni OCR ile okur.",
        {
            "path": {"type": "STRING"},
            "mode": {"type": "STRING"},
            "languageHint": {"type": "STRING"},
        },
        ["path"],
    ),
    _tool_decl(
        "image_read",
        "Yerel görsel dosyasını güvenli şekilde inceler.",
        {"path": {"type": "STRING"}, "mode": {"type": "STRING"}},
        ["path"],
    ),
    _tool_decl(
        "image_generate",
        "OpenAI Images API ile görsel üretir ve güvenli çıktı dosyası yazar.",
        {
            "prompt": {"type": "STRING"},
            "outputPath": {"type": "STRING"},
            "title": {"type": "STRING"},
            "size": {"type": "STRING"},
            "quality": {"type": "STRING"},
            "background": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
        ["prompt"],
    ),
    _tool_decl(
        "image_fetch",
        "Herkese açık bir kaynaktan (Openverse/Wikimedia) bir konu için görsel indirir ve kullanıcının klasörüne (varsayılan masaüstü) kaydeder.",
        {
            "query": {"type": "STRING"},
            "destination": {"type": "STRING"},
            "count": {"type": "INTEGER"},
            "overwrite": {"type": "BOOLEAN"},
        },
        ["query"],
    ),
    _tool_decl(
        "file_read",
        "Bir metin/kod dosyasını güvenli şekilde okur (isteğe bağlı satır aralığı).",
        {
            "path": {"type": "STRING"},
            "max_bytes": {"type": "INTEGER"},
            "start_line": {"type": "INTEGER"},
            "end_line": {"type": "INTEGER"},
        },
        ["path"],
    ),
    _tool_decl(
        "file_search",
        "Bir klasör ağacında dosya içeriğinde metin/regex arar (ripgrep destekli).",
        {
            "query": {"type": "STRING"},
            "path": {"type": "STRING"},
            "glob": {"type": "STRING"},
            "regex": {"type": "BOOLEAN"},
            "case_sensitive": {"type": "BOOLEAN"},
            "max_results": {"type": "INTEGER"},
        },
        ["query"],
    ),
    _tool_decl(
        "directory_tree",
        "Proje/klasör yapısını (ağaç) çıkarır; gürültülü klasörleri atlar.",
        {
            "path": {"type": "STRING"},
            "max_depth": {"type": "INTEGER"},
            "max_entries": {"type": "INTEGER"},
        },
    ),
    _tool_decl(
        "git_status",
        "Bir git deposunun durumunu (branch + staged/unstaged/untracked) döndürür.",
        {"path": {"type": "STRING"}},
    ),
    _tool_decl(
        "git_diff",
        "Bir git deposundaki çalışma ağacı veya staged farkını (diff) döndürür.",
        {
            "path": {"type": "STRING"},
            "staged": {"type": "BOOLEAN"},
            "target_file": {"type": "STRING"},
        },
    ),
    _tool_decl(
        "file_write",
        "Bir metin/kod dosyası oluşturur veya (overwrite=true ile) üzerine yazar. Onay gerektirir.",
        {
            "path": {"type": "STRING"},
            "content": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
        ["path"],
    ),
    _tool_decl(
        "file_patch",
        "Var olan bir dosyada çıpalı bul/değiştir uygular (old_string → new_string). Onay gerektirir.",
        {
            "path": {"type": "STRING"},
            "old_string": {"type": "STRING"},
            "new_string": {"type": "STRING"},
            "replace_all": {"type": "BOOLEAN"},
        },
        ["path", "old_string"],
    ),
    _tool_decl(
        "git_commit",
        "Değişiklikleri commit'ler (opsiyonel git add -A). PUSH YAPMAZ. Onay gerektirir.",
        {
            "path": {"type": "STRING"},
            "message": {"type": "STRING"},
            "add_all": {"type": "BOOLEAN"},
        },
        ["message"],
    ),
    _tool_decl(
        "git_branch",
        "Yeni bir git branch'i oluşturur (varsayılan: oluşturup geçer). Onay gerektirir.",
        {
            "path": {"type": "STRING"},
            "name": {"type": "STRING"},
            "checkout": {"type": "BOOLEAN"},
        },
        ["name"],
    ),
    _tool_decl(
        "canvas_write",
        "Metin, tablo, grafik ve görselleri PDF veya PNG canvas çıktısına dönüştürür.",
        {
            "prompt": {"type": "STRING"},
            "outputPath": {"type": "STRING"},
            "title": {"type": "STRING"},
            "blocks": {"type": "ARRAY"},
            "sections": {"type": "ARRAY"},
            "outputFormat": {"type": "STRING"},
            "width": {"type": "NUMBER"},
            "height": {"type": "NUMBER"},
            "sourceContext": {"type": "STRING"},
            "sourcePath": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
        ["outputPath"],
    ),
    _tool_decl(
        "data_analyze",
        "CSV veya JSON verisini yerel olarak analiz eder.",
        {
            "path": {"type": "STRING"},
            "mode": {"type": "STRING"},
            "columns": {"type": "ARRAY"},
        },
        ["path"],
    ),
    _tool_decl(
        "chart_generate",
        "CSV veya JSON verisinden yerel PNG grafik üretir.",
        {
            "path": {"type": "STRING"},
            "chartType": {"type": "STRING"},
            "xColumn": {"type": "STRING"},
            "yColumn": {"type": "STRING"},
            "title": {"type": "STRING"},
        },
        ["path"],
    ),
    _tool_decl(
        "math_solve",
        "Yerel matematik ifadesini çözer veya sadeleştirir.",
        {
            "expression": {"type": "STRING"},
            "mode": {"type": "STRING"},
        },
        ["expression"],
    ),
    _tool_decl(
        "latex_parse",
        "LaTeX matematik ifadesini yerel sembolik forma çevirir.",
        {
            "expression": {"type": "STRING"},
            "mode": {"type": "STRING"},
        },
        ["expression"],
    ),
    _tool_decl(
        "quantum_model_problem",
        "Optimizasyon problemini QUBO/Ising demo modeline dönüştürür.",
        {
            "prompt": {"type": "STRING"},
            "problemClass": {"type": "STRING"},
        },
        ["prompt"],
    ),
    _tool_decl(
        "quantum_run_experiment",
        "QAOA/VQE simulator demo deneyini yürütür.",
        {
            "prompt": {"type": "STRING"},
            "algorithm": {"type": "STRING"},
            "shots": {"type": "NUMBER"},
        },
        ["prompt"],
    ),
    _tool_decl(
        "quantum_compare_classical",
        "Quantum demo sonucunu klasik baseline ile karşılaştırır.",
        {
            "prompt": {"type": "STRING"},
        },
        ["prompt"],
    ),
    _tool_decl(
        "quantum_generate_report",
        "Quantum deney akışı için teknik rapor ve metrik artifact üretir.",
        {
            "prompt": {"type": "STRING"},
            "title": {"type": "STRING"},
        },
        ["prompt"],
    ),
    _tool_decl(
        "document_write",
        "DOCX belge üretir veya dönüştürür.",
        {
            "prompt": {"type": "STRING"},
            "outputPath": {"type": "STRING"},
            "title": {"type": "STRING"},
            "sourcePath": {"type": "STRING"},
            "sourceContext": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
    ),
    _tool_decl(
        "spreadsheet_write",
        "XLSX çalışma sayfası üretir.",
        {
            "prompt": {"type": "STRING"},
            "outputPath": {"type": "STRING"},
            "title": {"type": "STRING"},
            "sourceContext": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
    ),
    _tool_decl(
        "presentation_write",
        "PPTX sunum üretir.",
        {
            "prompt": {"type": "STRING"},
            "outputPath": {"type": "STRING"},
            "title": {"type": "STRING"},
            "sourceContext": {"type": "STRING"},
            "overwrite": {"type": "BOOLEAN"},
        },
    ),
    _tool_decl(
        "retrieve_context",
        "Yerel çalışma alanı ve konuşmalardan bağlam eşleşmeleri döndürür.",
        {
            "query": {"type": "STRING"},
            "sources": {"type": "STRING"},
            "limit": {"type": "NUMBER"},
            "conversationId": {"type": "STRING"},
        },
        ["query"],
    ),
    _tool_decl(
        "speech_capture",
        "Yerel mikrofondan kısa ses kaydı başlatır veya durdurur.",
        {
            "action": {"type": "STRING"},
            "_uiGesture": {"type": "BOOLEAN"},
        },
        ["action"],
    ),
    _tool_decl(
        "speech_to_text",
        "Yerel ses kaydını metne çevirir.",
        {
            "audioPath": {"type": "STRING"},
            "sessionId": {"type": "STRING"},
            "languageHint": {"type": "STRING"},
            "taskId": {"type": "STRING"},
        },
    ),
    _tool_decl(
        "text_to_speech",
        "Metni yerel olarak sesli okur.",
        {
            "text": {"type": "STRING"},
            "languageHint": {"type": "STRING"},
            "voice": {"type": "STRING"},
            "interrupt": {"type": "BOOLEAN"},
        },
        ["text"],
    ),
    _tool_decl(
        "mcp_call_tool",
        "Yerel stdio MCP sunucusundaki bir aracı çağırır.",
        {
            "serverId": {"type": "STRING"},
            "toolName": {"type": "STRING"},
            "arguments": {"type": "OBJECT"},
        },
        ["serverId", "toolName"],
    ),
    _tool_decl(
        "run_skill",
        "Yerel skill manifestinden kontrollü bir skill çalıştırır.",
        {
            "skillId": {"type": "STRING"},
            "payload": {"type": "OBJECT"},
        },
        ["skillId"],
    ),
    _tool_decl(
        "desktop_os.status",
        "Yerel desktop OS capability ve native entegrasyon durumunu döndürür.",
        {},
    ),
    _tool_decl(
        "desktop_os.permissions",
        "Yerel desktop izin modelini ve izin readiness durumunu döndürür.",
        {},
    ),
    _tool_decl(
        "desktop_os.open_permission_settings",
        "İlgili sistem izin ekranını güvenli şekilde açar.",
        {
            "permission": {"type": "STRING"},
        },
    ),
    _tool_decl(
        "desktop_os.processes",
        "Yerel çalışan prosesleri güvenli şekilde listeler.",
        {
            "query": {"type": "STRING"},
            "limit": {"type": "NUMBER"},
        },
    ),
    _tool_decl(
        "desktop_os.active_window",
        "Aktif pencere bilgisini güvenli şekilde döndürür.",
        {},
    ),
    _tool_decl(
        "save_memory",
        "Kalıcı hafızaya bir kayıt ekler.",
        {"category": {"type": "STRING"}, "key": {"type": "STRING"}, "value": {"type": "STRING"}},
        ["key", "value"],
    ),
    _tool_decl(
        "delete_memory",
        "Kalıcı hafızadan kayıt siler.",
        {"category": {"type": "STRING"}, "key": {"type": "STRING"}, "match_text": {"type": "STRING"}},
    ),
    _tool_decl(
        "clipboard_read",
        "Panodaki (clipboard) metni okur.",
        {"query": {"type": "STRING"}},
    ),
    _tool_decl(
        "clipboard_write",
        "Verilen metni panoya (clipboard) kopyalar.",
        {"text": {"type": "STRING"}},
        ["text"],
    ),
]


_ADAPTER_SPECS: dict[str, _AdapterSpec] = {
    "open_app": _AdapterSpec("actions.open_app", "open_app"),
    "close_app": _AdapterSpec("actions.open_app", "close_app"),
    "sys_info": _AdapterSpec("actions.sys_info", "sys_info"),
    "get_weather": _AdapterSpec("actions.weather", "get_weather_summary"),
    "get_calendar_events": _AdapterSpec("actions.calendar", "get_calendar_events"),
    "add_calendar_event": _AdapterSpec("actions.calendar", "add_calendar_event"),
    "delete_calendar_event": _AdapterSpec("actions.calendar", "delete_calendar_event"),
    "get_reminders": _AdapterSpec("actions.reminders", "get_reminders"),
    "add_reminder": _AdapterSpec("actions.reminders", "add_reminder"),
    "browser_control": _AdapterSpec("actions.browser", "browser_control"),
    "web_research": _AdapterSpec("actions.web_research", "web_research"),
    "shell_run": _AdapterSpec("actions.shell", "shell_run"),
    "play_media": _AdapterSpec("actions.media", "play_media"),
    "analyze_screen": _AdapterSpec("actions.screen_vision", "analyze_screen"),
    "desktop_operator.observe_screen": _AdapterSpec("actions.desktop_operator", "observe_screen"),
    "desktop_operator.locate": _AdapterSpec("actions.desktop_operator", "locate"),
    "desktop_operator.focus_window": _AdapterSpec("actions.desktop_operator", "focus_window"),
    "desktop_operator.execute_action": _AdapterSpec("actions.desktop_operator", "execute_action"),
    "desktop_operator.run": _AdapterSpec("actions.desktop_operator", "run"),
    "desktop_operator.cancel": _AdapterSpec("actions.desktop_operator", "cancel"),
    "get_youtube_channel_report": _AdapterSpec("actions.youtube_stats", "get_youtube_channel_report"),
    "send_whatsapp_message": _AdapterSpec("actions.whatsapp", "send_whatsapp_message"),
    "save_whatsapp_contact": _AdapterSpec("actions.whatsapp", "save_whatsapp_contact"),
    "email_draft": _AdapterSpec("actions.email", "email_draft"),
    "email_send": _AdapterSpec("actions.email", "email_send"),
    "document_read": _AdapterSpec("actions.document_read", "document_read"),
    "ocr_read": _AdapterSpec("actions.ocr_read", "ocr_read"),
    "image_read": _AdapterSpec("actions.image_read", "image_read"),
    "image_generate": _AdapterSpec("actions.image_generate", "image_generate"),
    "image_fetch": _AdapterSpec("actions.image_fetch", "image_fetch"),
    "file_read": _AdapterSpec("actions.filesystem", "file_read"),
    "file_search": _AdapterSpec("actions.filesystem", "file_search"),
    "directory_tree": _AdapterSpec("actions.filesystem", "directory_tree"),
    "git_status": _AdapterSpec("actions.git_ops", "git_status"),
    "git_diff": _AdapterSpec("actions.git_ops", "git_diff"),
    "file_write": _AdapterSpec("actions.file_write", "file_write"),
    "file_patch": _AdapterSpec("actions.file_write", "file_patch"),
    "git_commit": _AdapterSpec("actions.git_ops", "git_commit"),
    "git_branch": _AdapterSpec("actions.git_ops", "git_branch"),
    "canvas_write": _AdapterSpec("actions.canvas_write", "canvas_write"),
    "data_analyze": _AdapterSpec("actions.data_analyze", "data_analyze"),
    "chart_generate": _AdapterSpec("actions.chart_generate", "chart_generate"),
    "math_solve": _AdapterSpec("actions.math_solve", "math_solve"),
    "latex_parse": _AdapterSpec("actions.latex_parse", "latex_parse"),
    "quantum_model_problem": _AdapterSpec("actions.quantum", "quantum_model_problem"),
    "quantum_run_experiment": _AdapterSpec("actions.quantum", "quantum_run_experiment"),
    "quantum_compare_classical": _AdapterSpec("actions.quantum", "quantum_compare_classical"),
    "quantum_generate_report": _AdapterSpec("actions.quantum", "quantum_generate_report"),
    "document_write": _AdapterSpec("actions.document_write", "document_write"),
    "spreadsheet_write": _AdapterSpec("actions.spreadsheet_write", "spreadsheet_write"),
    "presentation_write": _AdapterSpec("actions.presentation_write", "presentation_write"),
    "retrieve_context": _AdapterSpec("actions.retrieve_context", "retrieve_context"),
    "speech_capture": _AdapterSpec("actions.speech", "speech_capture"),
    "speech_to_text": _AdapterSpec("actions.speech", "speech_to_text"),
    "text_to_speech": _AdapterSpec("actions.tts", "text_to_speech"),
    "mcp_call_tool": _AdapterSpec("actions.mcp_tool", "mcp_call_tool"),
    "desktop_os_status": _AdapterSpec("actions.desktop_os", "desktop_os_status"),
    "desktop_os_permissions": _AdapterSpec("actions.desktop_os", "desktop_os_permissions"),
    "desktop_os_open_permission_settings": _AdapterSpec("actions.desktop_os", "desktop_os_open_permission_settings"),
    "desktop_os_processes": _AdapterSpec("actions.desktop_os", "desktop_os_processes"),
    "desktop_os_active_window": _AdapterSpec("actions.desktop_os", "desktop_os_active_window"),
    "update_memory": _AdapterSpec("memory.memory_manager", "update_memory"),
    "delete_memory": _AdapterSpec("memory.memory_manager", "delete_memory"),
    "clipboard_read": _AdapterSpec("actions.clipboard", "clipboard_read"),
    "clipboard_write": _AdapterSpec("actions.clipboard", "clipboard_write"),
}


def capability_names() -> set[str]:
    return {str(item["name"]) for item in TOOL_DECLARATIONS}


_DARWIN_ONLY_CAPABILITIES = {
    "open_app",
    "close_app",
    "get_calendar_events",
    "add_calendar_event",
    "delete_calendar_event",
    "get_reminders",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "analyze_screen",
    "desktop_operator.observe_screen",
    "desktop_operator.locate",
    "desktop_operator.focus_window",
    "desktop_operator.execute_action",
    "desktop_operator.run",
    "desktop_operator.cancel",
    "clipboard_read",
    "clipboard_write",
}
_WRITE_CAPABILITIES = {
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "image_generate",
    "chart_generate",
}
_SIDE_EFFECT_CAPABILITIES = {
    "open_app",
    "close_app",
    "shell_run",
    "desktop_operator.focus_window",
    "desktop_operator.execute_action",
    "desktop_operator.run",
    "desktop_operator.cancel",
    "add_calendar_event",
    "delete_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "email_send",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "image_generate",
    "chart_generate",
    "run_skill",
    "mcp_call_tool",
    "file_write",
    "file_patch",
    "git_commit",
    "git_branch",
}
_NON_RETRYABLE_SIDE_EFFECTS = {
    "open_app",
    "close_app",
    "shell_run",
    "add_calendar_event",
    "delete_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "email_send",
    "file_patch",
    "git_commit",
    "git_branch",
}
_CAPABILITY_DEPENDENCY_KEYS: dict[str, tuple[str, ...]] = {
    "web_research": ("httpx",),
    "ocr_read": (),
    "image_read": ("pillow",),
    "math_solve": ("sympy",),
    "latex_parse": ("latex2sympy2_extended",),
    "data_analyze": ("pandas",),
    "chart_generate": ("pandas", "matplotlib"),
    "document_write": ("python_docx",),
    "spreadsheet_write": ("openpyxl",),
    "presentation_write": ("python_pptx",),
    "canvas_write": ("reportlab", "pillow"),
    "browser_control": ("requests",),
    "image_fetch": ("requests",),
    "speech_to_text": ("faster_whisper", "soundfile"),
    "text_to_speech": (),
    "mcp_call_tool": ("mcp",),
    "desktop_operator.observe_screen": ("pillow",),
    "desktop_operator.locate": ("pillow",),
    "desktop_operator.focus_window": (),
    "desktop_operator.execute_action": (),
    "desktop_operator.run": ("pillow",),
    "desktop_operator.cancel": (),
    "quantum_model_problem": ("qiskit",),
    "quantum_run_experiment": ("qiskit", "qiskit_aer"),
    "quantum_compare_classical": ("qiskit", "qiskit_aer"),
    "quantum_generate_report": ("qiskit",),
}


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except Exception:
        return False


def _piper_ready() -> bool:
    binary = str(os.environ.get("ELYAN_PIPER_BINARY", "") or "").strip() or (shutil.which("piper") or "")
    model = str(os.environ.get("ELYAN_PIPER_MODEL_PATH", "") or "").strip()
    return bool(binary and model and Path(model).expanduser().exists())


def dependency_status_snapshot() -> dict[str, dict[str, Any]]:
    return {
        "pymupdf": {"available": _module_available("fitz"), "label": "PyMuPDF"},
        "pypdf": {"available": _module_available("pypdf"), "label": "pypdf"},
        "markitdown": {"available": _module_available("markitdown"), "label": "MarkItDown"},
        "mammoth": {"available": _module_available("mammoth"), "label": "Mammoth"},
        "sympy": {"available": _module_available("sympy"), "label": "SymPy"},
        "pandas": {"available": _module_available("pandas"), "label": "pandas"},
        "matplotlib": {"available": _module_available("matplotlib"), "label": "matplotlib"},
        "latex2sympy2_extended": {
            "available": _module_available("latex2sympy2_extended"),
            "label": "latex2sympy2_extended",
        },
        "python_docx": {"available": _module_available("docx"), "label": "python-docx"},
        "openpyxl": {"available": _module_available("openpyxl"), "label": "openpyxl"},
        "python_pptx": {"available": _module_available("pptx"), "label": "python-pptx"},
        "reportlab": {"available": _module_available("reportlab"), "label": "ReportLab"},
        "sentence_transformers": {
            "available": _module_available("sentence_transformers"),
            "label": "sentence-transformers",
        },
        "httpx": {
            "available": _module_available("httpx"),
            "label": "httpx",
        },
        "requests": {
            "available": _module_available("requests"),
            "label": "requests",
        },
        "trafilatura": {
            "available": _module_available("trafilatura"),
            "label": "trafilatura",
        },
        "playwright": {
            "available": _module_available("playwright"),
            "label": "Playwright",
        },
        "opencv_python": {
            "available": _module_available("cv2"),
            "label": "OpenCV",
        },
        "pillow": {
            "available": _module_available("PIL"),
            "label": "Pillow",
        },
        "numpy": {
            "available": _module_available("numpy"),
            "label": "NumPy",
        },
        "faster_whisper": {
            "available": _module_available("faster_whisper"),
            "label": "faster-whisper",
        },
        "sounddevice": {
            "available": _module_available("sounddevice"),
            "label": "sounddevice",
        },
        "soundfile": {
            "available": _module_available("soundfile"),
            "label": "soundfile",
        },
        "piper": {
            "available": _piper_ready(),
            "label": "Piper",
        },
        "tesseract": {
            "available": bool(shutil.which("tesseract")),
            "label": "Tesseract OCR",
        },
        "easyocr": {
            "available": _module_available("easyocr"),
            "label": "EasyOCR",
        },
        "mcp": {
            "available": _module_available("mcp"),
            "label": "MCP Python SDK",
        },
        "langgraph": {
            "available": _module_available("langgraph"),
            "label": "LangGraph",
        },
        "litellm": {
            "available": _module_available("litellm"),
            "label": "LiteLLM",
        },
        "qiskit": {
            "available": _module_available("qiskit"),
            "label": "Qiskit",
        },
        "qiskit_aer": {
            "available": _module_available("qiskit_aer"),
            "label": "Qiskit Aer",
        },
        "dimod": {
            "available": _module_available("dimod"),
            "label": "dimod",
        },
        "ocean_sdk": {
            "available": _module_available("dwave.system"),
            "label": "Ocean SDK",
        },
    }


def _runtime_capability_state_aliases(name: str) -> tuple[str, ...]:
    aliases = {str(name or "").strip()}
    if "_" in name:
        aliases.add(name.replace("_", "."))
    if "." in name:
        aliases.add(name.replace(".", "_"))
    return tuple(alias for alias in aliases if alias)


def capability_readiness(
    name: str,
    *,
    state: dict[str, Any] | None = None,
    dependency_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = capability_metadata(name)
    normalized = str(metadata.get("name", "") or "").strip()
    system_permission = _system_permission_detail_for_capability(normalized, allow_probe=False)
    if not normalized:
        return {
            "available": False,
            "ready": False,
            "errorCode": "UNKNOWN_CAPABILITY",
            "dependencyKeys": [],
            "missingDependencies": [],
            "degradationReason": "unknown_capability",
        }

    runtime = state.get("runtime", {}) if isinstance(state, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    runtime_states = runtime.get("capabilityStates", {})
    runtime_states = runtime_states if isinstance(runtime_states, dict) else {}
    for alias in _runtime_capability_state_aliases(normalized):
        observed = runtime_states.get(alias)
        if isinstance(observed, dict) and (
            observed.get("ready") is False or observed.get("available") is False
        ):
            observed_error = str(observed.get("errorCode", "") or "CAPABILITY_UNAVAILABLE")
            if normalized.startswith("desktop_operator.") and observed_error in {"", "CAPABILITY_UNAVAILABLE", "native_snapshot_unavailable", "desktop_operator_unavailable"}:
                dependency = capability_dependency_status(normalized)
                if dependency.get("available") is True:
                    break
            return {
                **metadata,
                "available": bool(observed.get("available", False)),
                "ready": bool(observed.get("ready", False)),
                "errorCode": observed_error,
                "missingDependencies": list(observed.get("missingDependencies", []) or []),
                "dependencyReady": bool(observed.get("available", False)),
                "platformSupported": True,
                "degradationReason": observed_error.lower() or "capability_unavailable",
                **system_permission,
            }

    supported_platforms = metadata.get("supportedPlatforms", [])
    if isinstance(supported_platforms, list) and supported_platforms and sys.platform not in supported_platforms:
        return {
            **metadata,
            "available": False,
            "ready": False,
            "errorCode": "UNSUPPORTED_PLATFORM",
            "missingDependencies": [],
            "dependencyReady": True,
            "platformSupported": False,
            "degradationReason": "unsupported_platform",
            **system_permission,
        }

    dependencies = metadata.get("dependencyKeys", [])
    dependencies = [str(item or "").strip() for item in dependencies if str(item or "").strip()]
    snapshot = dependency_status if isinstance(dependency_status, dict) else dependency_status_snapshot()
    missing = [
        key
        for key in dependencies
        if not bool((snapshot.get(key) or {}).get("available", False))
    ]
    readiness = {
        **metadata,
        "available": not missing,
        "ready": not missing,
        "errorCode": "DEPENDENCY_UNAVAILABLE" if missing else "",
        "missingDependencies": missing,
        "dependencyReady": not missing,
        "platformSupported": True,
        "degradationReason": "dependency_unavailable" if missing else "",
        **system_permission,
    }
    os_permission_status = str(readiness.get("osPermissionStatus", "") or "").strip().lower()
    if os_permission_status in {"required", "denied"} and str(readiness.get("permissionClass", "") or "") != "read_only":
        readiness["available"] = False
        readiness["ready"] = False
        readiness["errorCode"] = "OS_PERMISSION_REQUIRED"
        readiness["degradationReason"] = "os_permission_required"
    return readiness


def capability_metadata(name: str) -> dict[str, Any]:
    normalized = str(name or "").strip()
    if not normalized:
        return CapabilityMetadata(
            name="",
            category="other",
            side_effect=False,
            required_permissions=(),
            permission_class="blocked",
            supported_platforms=("darwin", "win32", "linux"),
            dependency_keys=(),
            timeout_seconds=60,
            verification_mode="tool_result",
            preferred_model_class="reasoning",
            retryable=False,
        ).to_dict()

    category = "other"
    if normalized in {"file_read", "file_search", "directory_tree", "git_status", "git_diff", "file_write", "file_patch", "git_commit", "git_branch"}:
        category = "developer"
    elif normalized in {"web_research", "retrieve_context", "document_read", "ocr_read", "image_read", "image_fetch"}:
        category = "research_docs"
    elif normalized in {"document_write", "spreadsheet_write", "presentation_write", "canvas_write", "image_generate", "chart_generate"}:
        category = "research_docs"
    elif normalized in {"email_draft", "email_send", "send_whatsapp_message", "save_whatsapp_contact", "add_calendar_event", "delete_calendar_event", "get_calendar_events", "get_reminders", "add_reminder", "run_skill", "mcp_call_tool"}:
        category = "communication_approval"
    elif normalized in {"math_solve", "latex_parse", "quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical", "quantum_generate_report"}:
        category = "math_quantum"
    elif normalized in {"open_app", "close_app", "sys_info", "browser_control", "play_media", "analyze_screen", "shell_run", "desktop_os.status", "desktop_os.permissions", "desktop_os.open_permission_settings", "desktop_os.processes", "desktop_os.active_window", "speech_capture", "speech_to_text", "text_to_speech", "clipboard_read", "clipboard_write"}:
        category = "local_execution"
    elif normalized.startswith("desktop_operator."):
        category = "local_execution"

    permissions: tuple[str, ...] = ()
    if normalized in {"browser_control", "play_media"}:
        permissions = ("allow_browser_control",)
    elif normalized == "analyze_screen":
        permissions = ("allow_screen_analysis",)
    elif normalized in {"desktop_operator.observe_screen", "desktop_operator.locate"}:
        permissions = ("allow_screen_analysis",)
    elif normalized in {"desktop_operator.focus_window", "desktop_operator.execute_action", "desktop_operator.run"}:
        permissions = ("allow_computer_control",)
    elif normalized == "desktop_operator.cancel":
        permissions = ()
    elif normalized == "shell_run":
        permissions = ("allow_shell",)
    elif normalized in {"desktop_os.processes", "desktop_os.active_window"}:
        permissions = ("allow_system_inspection",)
    elif normalized in {"add_calendar_event", "delete_calendar_event", "add_reminder", "send_whatsapp_message", "save_whatsapp_contact"}:
        permissions = ("allow_personal_actions",)
    elif normalized in _WRITE_CAPABILITIES or normalized in {"email_send", "mcp_call_tool", "run_skill"}:
        permissions = ("allow_destructive_tools",)

    permission_class = "blocked"
    if normalized in _SIDE_EFFECT_CAPABILITIES:
        permission_class = "approval_required"
    elif permissions:
        permission_class = "degraded_but_safe"
    else:
        permission_class = "read_only"

    supported_platforms = ("darwin",) if normalized in _DARWIN_ONLY_CAPABILITIES else ("darwin", "win32", "linux")
    verification_mode = "tool_result"
    if normalized == "open_app":
        verification_mode = "foreground_confirmed"
    elif normalized == "close_app":
        verification_mode = "close_confirmed"
    elif normalized == "browser_control":
        verification_mode = "browser_handoff"
    elif normalized == "play_media":
        verification_mode = "media_handoff"
    elif normalized == "analyze_screen":
        verification_mode = "screen_analysis"
    elif normalized == "desktop_operator.observe_screen":
        verification_mode = "screen_observation"
    elif normalized == "desktop_operator.locate":
        verification_mode = "target_located"
    elif normalized in {"desktop_operator.focus_window", "desktop_operator.execute_action", "desktop_operator.run"}:
        verification_mode = "operator_verified"
    elif normalized == "desktop_operator.cancel":
        verification_mode = "operator_cancelled"
    if normalized in _WRITE_CAPABILITIES or normalized in {"image_fetch", "file_write", "file_patch"}:
        verification_mode = "artifact_exists"
    elif normalized in {"document_read", "ocr_read", "image_read", "data_analyze", "math_solve", "latex_parse", "speech_to_text", "text_to_speech", "web_research", "retrieve_context", "email_draft", "quantum_model_problem", "quantum_compare_classical", "quantum_generate_report", "clipboard_read", "file_read", "file_search", "directory_tree", "git_status", "git_diff", "git_commit", "git_branch"}:
        verification_mode = "result_nonempty"
    elif normalized in {"speech_capture"}:
        verification_mode = "none"

    preferred_model_class = "reasoning"
    if normalized in {"image_read", "ocr_read", "analyze_screen", "desktop_operator.observe_screen", "desktop_operator.locate"}:
        preferred_model_class = "vision"
    elif normalized in {"speech_to_text", "text_to_speech", "speech_capture"}:
        preferred_model_class = "audio"
    elif normalized in {"document_read", "document_write", "spreadsheet_write", "presentation_write", "canvas_write"}:
        preferred_model_class = "document"
    elif normalized.startswith("quantum_"):
        preferred_model_class = "reasoning"

    dependency_keys = _CAPABILITY_DEPENDENCY_KEYS.get(normalized, ())
    timeout_seconds = 60
    if normalized in {"web_research", "document_write", "spreadsheet_write", "presentation_write", "canvas_write", "quantum_run_experiment", "image_generate", "image_fetch", "ocr_read", "file_search", "desktop_operator.observe_screen", "desktop_operator.locate", "desktop_operator.execute_action", "desktop_operator.run"}:
        timeout_seconds = 120
    elif normalized == "shell_run":
        timeout_seconds = 180

    retryable = normalized not in _NON_RETRYABLE_SIDE_EFFECTS
    return CapabilityMetadata(
        name=normalized,
        category=category,
        side_effect=normalized in _SIDE_EFFECT_CAPABILITIES,
        required_permissions=permissions,
        permission_class=permission_class,
        supported_platforms=supported_platforms,
        dependency_keys=dependency_keys,
        timeout_seconds=timeout_seconds,
        verification_mode=verification_mode,
        preferred_model_class=preferred_model_class,
        retryable=retryable,
    ).to_dict()


def capability_metadata_summary(enabled_capabilities: list[str] | set[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    available = sorted(capability_names()) if enabled_capabilities is None else sorted({str(item or "").strip() for item in enabled_capabilities if str(item or "").strip()})
    categories: dict[str, int] = {}
    verification_modes: dict[str, int] = {}
    side_effect_count = 0
    read_only_count = 0
    for capability in available:
        metadata = capability_metadata(capability)
        category = str(metadata.get("category", "other") or "other")
        verification_mode = str(metadata.get("verificationMode", "tool_result") or "tool_result")
        categories[category] = categories.get(category, 0) + 1
        verification_modes[verification_mode] = verification_modes.get(verification_mode, 0) + 1
        if metadata.get("sideEffect") is True:
            side_effect_count += 1
        else:
            read_only_count += 1
    return {
        "total": len(available),
        "sideEffectCount": side_effect_count,
        "readOnlyCount": read_only_count,
        "categories": categories,
        "verificationModes": verification_modes,
    }


_CAPABILITY_GROUP_DEFINITIONS: tuple[tuple[str, str, set[str]], ...] = (
    (
        "research_docs",
        "Araştırma / Doküman",
        {
            "web_research",
            "retrieve_context",
            "document_read",
            "ocr_read",
            "image_read",
            "image_generate",
            "image_fetch",
            "data_analyze",
            "chart_generate",
            "document_write",
            "spreadsheet_write",
            "presentation_write",
            "canvas_write",
        },
    ),
    (
        "communication_approval",
        "İletişim / Onay",
        {
            "email_draft",
            "email_send",
            "send_whatsapp_message",
            "save_whatsapp_contact",
            "add_calendar_event",
            "delete_calendar_event",
            "get_calendar_events",
            "get_reminders",
            "add_reminder",
            "run_skill",
            "mcp_call_tool",
        },
    ),
    (
        "math_quantum",
        "Matematik / Quantum",
        {
            "math_solve",
            "latex_parse",
            "quantum_model_problem",
            "quantum_run_experiment",
            "quantum_compare_classical",
            "quantum_generate_report",
        },
    ),
    (
        "developer",
        "Geliştirme / Kod",
        {
            "file_read",
            "file_search",
            "directory_tree",
            "git_status",
            "git_diff",
            "file_write",
            "file_patch",
            "git_commit",
            "git_branch",
        },
    ),
    (
        "local_execution",
        "Yerel Yürütme",
        {
            "open_app",
            "close_app",
            "browser_control",
            "play_media",
            "analyze_screen",
            "desktop_operator.observe_screen",
            "desktop_operator.locate",
            "desktop_operator.focus_window",
            "desktop_operator.execute_action",
            "desktop_operator.run",
            "desktop_operator.cancel",
            "shell_run",
            "speech_capture",
            "speech_to_text",
            "text_to_speech",
            "desktop_os.status",
            "desktop_os.permissions",
            "desktop_os.open_permission_settings",
            "desktop_os.processes",
            "desktop_os.active_window",
            "save_memory",
            "delete_memory",
            "sys_info",
            "get_weather",
        },
    ),
)


def capability_groups(
    enabled_capabilities: set[str] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    available = capability_names()
    if isinstance(enabled_capabilities, list):
        available = {_normalize_capability_name(item) for item in enabled_capabilities if str(item or "").strip()}
    elif isinstance(enabled_capabilities, set):
        available = {_normalize_capability_name(item) for item in enabled_capabilities if str(item or "").strip()}

    groups: dict[str, dict[str, Any]] = {}
    for group_id, label, members in _CAPABILITY_GROUP_DEFINITIONS:
        selected = sorted(item for item in members if item in available)
        if not selected:
            continue
        groups[group_id] = {
            "label": label,
            "capabilities": selected,
            "count": len(selected),
        }
    return groups


def capability_dependency_status(capability_name: str) -> dict[str, Any]:
    raw_name = str(capability_name or "").strip()
    normalized = raw_name if raw_name in _ADAPTER_SPECS else _normalize_capability_name(raw_name)
    if normalized not in _ADAPTER_SPECS and raw_name.startswith("desktop.operator."):
        dotted_alias = "desktop_operator." + raw_name.removeprefix("desktop.operator.")
        if dotted_alias in _ADAPTER_SPECS:
            normalized = dotted_alias
    if not normalized:
        return {
            "capability": "",
            "available": False,
            "lastErrorCode": "UNKNOWN_CAPABILITY",
            "lastErrorMessage": "Bilinmeyen capability.",
        }

    spec = _ADAPTER_SPECS.get(normalized)
    if spec is None:
        return {
            "capability": normalized,
            "available": False,
            "lastErrorCode": "UNKNOWN_CAPABILITY",
            "lastErrorMessage": "Bilinmeyen capability.",
        }

    try:
        module = import_module(spec.module)
    except ModuleNotFoundError as exc:
        return {
            "capability": normalized,
            "available": False,
            "lastErrorCode": "DEPENDENCY_UNAVAILABLE",
            "lastErrorMessage": "Bu özellik bu kurulumda hazır değil.",
            "module": spec.module,
            "attribute": spec.attribute,
            "detail": _string_from_exception(exc),
        }
    except ImportError as exc:
        return {
            "capability": normalized,
            "available": False,
            "lastErrorCode": "CAPABILITY_UNAVAILABLE",
            "lastErrorMessage": "Bu özellik güvenli şekilde başlatılamadı.",
            "module": spec.module,
            "attribute": spec.attribute,
            "detail": _string_from_exception(exc),
        }

    handler = getattr(module, spec.attribute, None)
    if handler is None or not callable(handler):
        return {
            "capability": normalized,
            "available": False,
            "lastErrorCode": "CAPABILITY_UNAVAILABLE",
            "lastErrorMessage": "Bu özellik için geçerli adapter bulunamadı.",
            "module": spec.module,
            "attribute": spec.attribute,
        }

    status_function_names: list[str] = [f"{spec.attribute}_status"]
    if spec.module == "actions.quantum":
        status_function_names.insert(0, "quantum_runtime_status")
    elif spec.module == "actions.retrieve_context":
        status_function_names.insert(0, "retrieval_status")
    elif spec.module == "actions.speech":
        status_function_names.insert(0, "speech_runtime_status")
    elif spec.module == "actions.tts":
        status_function_names.insert(0, "speech_tts_status")
    elif spec.module == "actions.mcp_tool":
        status_function_names.insert(0, "mcp_tool_status")
    elif spec.module == "actions.desktop_os":
        status_function_names.insert(0, "desktop_os_runtime_status")
    elif spec.module == "actions.desktop_operator":
        status_function_names.insert(0, "operator_runtime_status")

    for status_function_name in status_function_names:
        status_fn = getattr(module, status_function_name, None)
        if not callable(status_fn):
            continue
        try:
            status_payload = status_fn()
        except Exception as exc:
            return {
                "capability": normalized,
                "available": False,
                "lastErrorCode": "CAPABILITY_UNAVAILABLE",
                "lastErrorMessage": "Bu özellik güvenli şekilde başlatılamadı.",
                "module": spec.module,
                "attribute": spec.attribute,
                "detail": _string_from_exception(exc),
            }
        if isinstance(status_payload, dict):
            status_available = bool(status_payload.get("available", True))
            if not status_available:
                return {
                    "capability": normalized,
                    "available": False,
                    "lastErrorCode": str(status_payload.get("lastErrorCode", "") or "CAPABILITY_UNAVAILABLE"),
                    "lastErrorMessage": str(
                        status_payload.get("lastErrorMessage", "") or "Bu özellik güvenli şekilde başlatılamadı."
                    ),
                    "module": spec.module,
                    "attribute": spec.attribute,
                    "detail": status_payload,
                }
            return {
                "capability": normalized,
                "available": True,
                "lastErrorCode": "",
                "lastErrorMessage": "",
                "module": spec.module,
                "attribute": spec.attribute,
                "detail": status_payload,
            }

    return {
        "capability": normalized,
        "available": True,
        "lastErrorCode": "",
        "lastErrorMessage": "",
        "module": spec.module,
        "attribute": spec.attribute,
    }


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _writer_source_context(args: dict[str, Any]) -> str:
    """Yazıcı araçlar (document/spreadsheet/presentation/canvas) için içerik
    bağlamı: açık sourceContext yoksa zincirdeki önceki adımın çıktısına düşer.
    Böylece "araştır ve belgele" gibi çok adımlı planlarda rapor, araştırma
    içeriğiyle dolu üretilir — boş şablon değil."""
    explicit = str(args.get("sourceContext", "") or args.get("source_context", "") or "").strip()
    if explicit:
        return explicit
    previous = args.get("_previousResult")
    if isinstance(previous, dict):
        parts: list[str] = []
        for key in ("summary", "text", "body", "output"):
            value = str(previous.get(key, "") or "").strip()
            if value:
                parts.append(value)
                break
        bullets = previous.get("bullets")
        if isinstance(bullets, list):
            cleaned = [str(item).strip() for item in bullets if str(item).strip()]
            if cleaned:
                parts.append("\n".join(f"- {item}" for item in cleaned))
        sources = previous.get("sources")
        if isinstance(sources, list):
            lines = []
            for source in sources:
                if isinstance(source, dict):
                    label = str(source.get("title", "") or source.get("url", "") or "").strip()
                    snippet = str(source.get("snippet", "") or source.get("summary", "") or "").strip()
                    if label or snippet:
                        lines.append(f"- {label}: {snippet}".rstrip(": "))
            if lines:
                parts.append("Kaynaklar:\n" + "\n".join(lines))
        if parts:
            return "\n\n".join(parts)
    return str(args.get("_previousOutput", "") or "").strip()


def _string_from_exception(exc: Exception) -> str:
    return " ".join(str(exc or "").split()).strip()[:160]


@lru_cache(maxsize=None)
def _load_adapter(adapter_name: str) -> Callable[..., Any]:
    spec = _ADAPTER_SPECS.get(adapter_name)
    if spec is None:
        raise CapabilityLoadError("UNKNOWN_CAPABILITY", "Bilinmeyen araç.")
    try:
        module = import_module(spec.module)
    except ModuleNotFoundError as exc:
        raise CapabilityLoadError(
            "DEPENDENCY_UNAVAILABLE",
            "Bu özellik bu kurulumda hazır değil.",
        ) from exc
    except ImportError as exc:
        raise CapabilityLoadError(
            "CAPABILITY_UNAVAILABLE",
            "Bu özellik güvenli şekilde başlatılamadı.",
        ) from exc

    handler = getattr(module, spec.attribute, None)
    if handler is None or not callable(handler):
        raise CapabilityLoadError(
            "CAPABILITY_UNAVAILABLE",
            "Bu özellik için geçerli adapter bulunamadı.",
        )
    return handler


def _save_memory(args: dict[str, Any]) -> str:
    category = str(args.get("category", "notes") or "notes")
    key = str(args.get("key", "") or "").strip()
    value = str(args.get("value", "") or "").strip()
    if not key or not value:
        return "Kategori, anahtar veya değer eksik."
    _load_adapter("update_memory")({category: {key: {"value": value}}})
    return "Hafıza kaydedildi."


def _delete_memory(args: dict[str, Any]) -> str:
    return _load_adapter("delete_memory")(
        str(args.get("category", "") or ""),
        str(args.get("key", "") or ""),
        str(args.get("match_text", "") or ""),
    )


def _handlers() -> dict[str, Callable[[dict[str, Any]], str]]:
    return {
        "open_app": lambda args: _load_adapter("open_app")(str(args.get("app_name", ""))),
        "close_app": lambda args: _load_adapter("close_app")(str(args.get("app_name", ""))),
        "sys_info": lambda args: _load_adapter("sys_info")(str(args.get("query", "all") or "all")),
        "get_weather": lambda args: _load_adapter("get_weather")(args.get("location") or None),
        "get_calendar_events": lambda args: _load_adapter("get_calendar_events")(
            str(args.get("query", "today") or "today"),
            _as_int(args.get("limit"), 6),
        ),
        "add_calendar_event": lambda args: _load_adapter("add_calendar_event")(
            str(args.get("title", "")),
            str(args.get("start_iso", "")),
            str(args.get("end_iso", "") or ""),
            str(args.get("notes", "") or ""),
            str(args.get("location", "") or ""),
            str(args.get("calendar_name", "") or ""),
            bool(args.get("all_day", False)),
        ),
        "delete_calendar_event": lambda args: _load_adapter("delete_calendar_event")(
            str(args.get("title", "")),
            str(args.get("start_iso", "") or ""),
            str(args.get("calendar_name", "") or ""),
            bool(args.get("delete_all_matches", False)),
        ),
        "get_reminders": lambda args: _load_adapter("get_reminders")(
            str(args.get("query", "upcoming") or "upcoming"),
            _as_int(args.get("limit"), 8),
            str(args.get("list_name", "") or ""),
        ),
        "add_reminder": lambda args: _load_adapter("add_reminder")(
            str(args.get("title", "")),
            str(args.get("due_iso", "") or ""),
            str(args.get("notes", "") or ""),
            str(args.get("list_name", "") or ""),
            str(args.get("priority", "") or ""),
            bool(args.get("all_day", False)),
        ),
        "browser_control": lambda args: _load_adapter("browser_control")(
            str(args.get("action", "") or ""),
            url=str(args.get("url", "") or ""),
            query=str(args.get("query", "") or ""),
        ),
        "web_research": lambda args: _load_adapter("web_research")(
            str(args.get("query", "") or ""),
            _as_int(args.get("max_results"), 4),
            str(args.get("languageHint", "") or args.get("language_hint", "") or ""),
        ),
        "shell_run": lambda args: _load_adapter("shell_run")(
            str(args.get("command", "") or ""),
            int(args.get("timeout", 30) or 30),
            use_shell=bool(args.get("use_shell", False)),
            working_dir=str(args.get("working_dir", "") or args.get("workingDir", "") or ""),
            mode=str(args.get("mode", "") or "confirmed"),
        ),
        "play_media": lambda args: _load_adapter("play_media")(
            str(args.get("query", "") or ""),
            str(args.get("provider", "auto") or "auto"),
            bool(args.get("autoplay", True)),
        ),
        "analyze_screen": lambda args: _load_adapter("analyze_screen")(
            str(args.get("query", "Ekranda ne var?") or "Ekranda ne var?"),
            str(args.get("target", "active_window") or "active_window"),
        ),
        "desktop_operator.observe_screen": lambda args: _load_adapter("desktop_operator.observe_screen")(
            str(args.get("query", "") or ""),
            str(args.get("target", "active_window") or "active_window"),
            bool(args.get("preserveScreenshot", True)),
        ),
        "desktop_operator.locate": lambda args: _load_adapter("desktop_operator.locate")(
            str(args.get("text", "") or args.get("targetText", "") or ""),
            str(args.get("elementType", "") or args.get("element_type", "") or ""),
            dict(args.get("bbox", {}) or {}) if isinstance(args.get("bbox", {}), dict) else None,
        ),
        "desktop_operator.focus_window": lambda args: _load_adapter("desktop_operator.focus_window")(
            str(args.get("appName", "") or args.get("app_name", "") or ""),
            str(args.get("bundleId", "") or args.get("bundle_id", "") or ""),
        ),
        "desktop_operator.execute_action": lambda args: _load_adapter("desktop_operator.execute_action")(
            str(args.get("actionType", "") or args.get("action_type", "") or ""),
            target_text=str(args.get("targetText", "") or args.get("target_text", "") or ""),
            element_type=str(args.get("elementType", "") or args.get("element_type", "") or ""),
            bbox=dict(args.get("bbox", {}) or {}) if isinstance(args.get("bbox", {}), dict) else None,
            text=str(args.get("text", "") or ""),
            keys=list(args.get("keys", []) or []) if isinstance(args.get("keys"), list) else None,
            delta=args.get("delta"),
            duration=args.get("duration"),
            app_name=str(args.get("appName", "") or args.get("app_name", "") or ""),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "desktop_operator.run": lambda args: _load_adapter("desktop_operator.run")(
            goal=str(args.get("goal", "") or ""),
            action=str(args.get("action", "") or ""),
            target_text=str(args.get("targetText", "") or args.get("target_text", "") or ""),
            text=str(args.get("text", "") or ""),
            element_type=str(args.get("elementType", "") or args.get("element_type", "") or ""),
            app_name=str(args.get("appName", "") or args.get("app_name", "") or ""),
            steps=list(args.get("steps", []) or []) if isinstance(args.get("steps"), list) else None,
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "desktop_operator.cancel": lambda args: _load_adapter("desktop_operator.cancel")(
            str(args.get("runId", "") or args.get("run_id", "") or ""),
            str(args.get("reason", "user_cancel") or "user_cancel"),
            str(args.get("source", "manual") or "manual"),
        ),
        "get_youtube_channel_report": lambda args: _load_adapter("get_youtube_channel_report")(
            str(args.get("query", "overview") or "overview"),
            str(args.get("handle", "") or ""),
            _as_int(args.get("video_limit"), 6),
        ),
        "send_whatsapp_message": lambda args: _load_adapter("send_whatsapp_message")(
            str(args.get("message", "") or ""),
            str(args.get("phone_number", "") or ""),
            str(args.get("recipient_name", "") or ""),
            bool(args.get("send_now", False)),
            str(args.get("app_target", "auto") or "auto"),
        ),
        "document_read": lambda args: _load_adapter("document_read")(
            str(args.get("path", "") or ""),
            str(args.get("mode", "read") or "read"),
            str(args.get("text", "") or args.get("content", "") or ""),
            list(args.get("_selectedPaths", []) or []),
        ),
        "ocr_read": lambda args: _load_adapter("ocr_read")(
            str(args.get("path", "") or ""),
            str(args.get("mode", "read") or "read"),
            str(args.get("languageHint", "") or args.get("language_hint", "") or ""),
            list(args.get("_selectedPaths", []) or []),
        ),
        "image_read": lambda args: _load_adapter("image_read")(
            str(args.get("path", "") or ""),
            str(args.get("mode", "summary") or "summary"),
            list(args.get("_selectedPaths", []) or []),
        ),
        "image_generate": lambda args: _load_adapter("image_generate")(
            prompt=str(args.get("prompt", "") or ""),
            outputPath=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            size=str(args.get("size", "1024x1024") or "1024x1024"),
            quality=str(args.get("quality", "auto") or "auto"),
            background=str(args.get("background", "auto") or "auto"),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "image_fetch": lambda args: _load_adapter("image_fetch")(
            query=str(args.get("query", "") or args.get("subject", "") or ""),
            destination=str(args.get("destination", "") or args.get("dest", "") or ""),
            count=_as_int(args.get("count"), 1),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "file_read": lambda args: _load_adapter("file_read")(
            str(args.get("path", "") or ""),
            _as_int(args.get("max_bytes") if args.get("max_bytes") is not None else args.get("maxBytes"), 400000),
            _as_int(args.get("start_line") if args.get("start_line") is not None else args.get("startLine"), 0),
            _as_int(args.get("end_line") if args.get("end_line") is not None else args.get("endLine"), 0),
        ),
        "file_search": lambda args: _load_adapter("file_search")(
            str(args.get("query", "") or ""),
            str(args.get("path", ".") or "."),
            str(args.get("glob", "") or ""),
            bool(args.get("regex", False)),
            bool(args.get("case_sensitive", False) or args.get("caseSensitive", False)),
            _as_int(args.get("max_results") if args.get("max_results") is not None else args.get("maxResults"), 50),
        ),
        "directory_tree": lambda args: _load_adapter("directory_tree")(
            str(args.get("path", ".") or "."),
            _as_int(args.get("max_depth") if args.get("max_depth") is not None else args.get("maxDepth"), 3),
            _as_int(args.get("max_entries") if args.get("max_entries") is not None else args.get("maxEntries"), 400),
        ),
        "git_status": lambda args: _load_adapter("git_status")(
            str(args.get("path", ".") or "."),
        ),
        "git_diff": lambda args: _load_adapter("git_diff")(
            str(args.get("path", ".") or "."),
            bool(args.get("staged", False)),
            str(args.get("target_file", "") or args.get("targetFile", "") or ""),
        ),
        "file_write": lambda args: _load_adapter("file_write")(
            str(args.get("path", "") or ""),
            str(args.get("content", "") or ""),
            overwrite=bool(args.get("overwrite", False)),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "file_patch": lambda args: _load_adapter("file_patch")(
            str(args.get("path", "") or ""),
            str(args.get("old_string", "") or args.get("oldString", "") or ""),
            str(args.get("new_string", "") or args.get("newString", "") or ""),
            replace_all=bool(args.get("replace_all", False) or args.get("replaceAll", False)),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "git_commit": lambda args: _load_adapter("git_commit")(
            str(args.get("path", ".") or "."),
            str(args.get("message", "") or ""),
            add_all=bool(args.get("add_all", True) if args.get("add_all") is not None else args.get("addAll", True)),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "git_branch": lambda args: _load_adapter("git_branch")(
            str(args.get("path", ".") or "."),
            str(args.get("name", "") or ""),
            checkout=bool(args.get("checkout", True) if args.get("checkout") is not None else True),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "data_analyze": lambda args: _load_adapter("data_analyze")(
            str(args.get("path", "") or ""),
            str(args.get("mode", "summary") or "summary"),
            args.get("columns") if isinstance(args.get("columns"), list) else None,
            list(args.get("_selectedPaths", []) or []),
        ),
        "chart_generate": lambda args: _load_adapter("chart_generate")(
            str(args.get("path", "") or ""),
            str(args.get("chartType", "") or args.get("chart_type", "") or "bar"),
            str(args.get("xColumn", "") or args.get("x_column", "") or ""),
            str(args.get("yColumn", "") or args.get("y_column", "") or ""),
            str(args.get("title", "") or ""),
            list(args.get("_selectedPaths", []) or []),
        ),
        "math_solve": lambda args: _load_adapter("math_solve")(
            str(args.get("expression", "") or ""),
            str(args.get("mode", "solve") or "solve"),
        ),
        "latex_parse": lambda args: _load_adapter("latex_parse")(
            str(args.get("expression", "") or ""),
            str(args.get("mode", "parse") or "parse"),
        ),
        "quantum_model_problem": lambda args: _load_adapter("quantum_model_problem")(
            prompt=str(args.get("prompt", "") or ""),
            problem_class=str(args.get("problemClass", "") or args.get("problem_class", "") or "optimization"),
        ),
        "quantum_run_experiment": lambda args: _load_adapter("quantum_run_experiment")(
            prompt=str(args.get("prompt", "") or ""),
            algorithm=str(args.get("algorithm", "") or "qaoa"),
            shots=_as_int(args.get("shots"), 1024),
            _previousResult=dict(args.get("_previousResult", {}) or {}) if isinstance(args.get("_previousResult", {}), dict) else None,
        ),
        "quantum_compare_classical": lambda args: _load_adapter("quantum_compare_classical")(
            prompt=str(args.get("prompt", "") or ""),
            _previousResult=dict(args.get("_previousResult", {}) or {}) if isinstance(args.get("_previousResult", {}), dict) else None,
        ),
        "quantum_generate_report": lambda args: _load_adapter("quantum_generate_report")(
            prompt=str(args.get("prompt", "") or ""),
            title=str(args.get("title", "") or "Elyan Quantum Deney Raporu"),
            _previousResult=dict(args.get("_previousResult", {}) or {}) if isinstance(args.get("_previousResult", {}), dict) else None,
        ),
        "document_write": lambda args: _load_adapter("document_write")(
            prompt=str(args.get("prompt", "") or ""),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            sections=args.get("sections") if isinstance(args.get("sections"), list) else None,
            blocks=args.get("blocks") if isinstance(args.get("blocks"), list) else None,
            source_path=str(args.get("sourcePath", "") or args.get("source_path", "") or ""),
            source_context=_writer_source_context(args),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "canvas_write": lambda args: _load_adapter("canvas_write")(
            prompt=str(args.get("prompt", "") or ""),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            blocks=args.get("blocks") if isinstance(args.get("blocks"), list) else None,
            sections=args.get("sections") if isinstance(args.get("sections"), list) else None,
            output_format=str(args.get("outputFormat", "") or args.get("output_format", "") or ""),
            width=args.get("width"),
            height=args.get("height"),
            theme=args.get("theme") if isinstance(args.get("theme"), dict) else None,
            source_context=_writer_source_context(args),
            source_path=str(args.get("sourcePath", "") or args.get("source_path", "") or ""),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "spreadsheet_write": lambda args: _load_adapter("spreadsheet_write")(
            prompt=str(args.get("prompt", "") or ""),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            columns=args.get("columns") if isinstance(args.get("columns"), list) else None,
            rows=args.get("rows") if isinstance(args.get("rows"), list) else None,
            source_context=_writer_source_context(args),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "presentation_write": lambda args: _load_adapter("presentation_write")(
            prompt=str(args.get("prompt", "") or ""),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            slides=args.get("slides") if isinstance(args.get("slides"), list) else None,
            blocks=args.get("blocks") if isinstance(args.get("blocks"), list) else None,
            source_context=_writer_source_context(args),
            overwrite=bool(args.get("overwrite", False)),
        ),
        "retrieve_context": lambda args: _load_adapter("retrieve_context")(
            str(args.get("query", "") or ""),
            args.get("sources"),
            _as_int(args.get("limit"), 6),
            str(args.get("conversationId", "") or args.get("conversation_id", "") or ""),
        ),
        "speech_capture": lambda args: _load_adapter("speech_capture")(
            str(args.get("action", "status") or "status"),
            bool(args.get("_uiGesture", False)),
        ),
        "speech_to_text": lambda args: _load_adapter("speech_to_text")(
            audio_path=str(args.get("audioPath", "") or args.get("audio_path", "") or ""),
            session_id=str(args.get("sessionId", "") or args.get("session_id", "") or ""),
            language_hint=str(args.get("languageHint", "") or args.get("language_hint", "") or ""),
            task_id=str(args.get("taskId", "") or args.get("task_id", "") or ""),
            _selectedPaths=list(args.get("_selectedPaths", []) or []),
        ),
        "text_to_speech": lambda args: _load_adapter("text_to_speech")(
            str(args.get("text", "") or ""),
            str(args.get("languageHint", "") or args.get("language_hint", "") or ""),
            str(args.get("voice", "") or ""),
            bool(args.get("interrupt", False)),
        ),
        "mcp_call_tool": lambda args: _load_adapter("mcp_call_tool")(
            str(args.get("serverId", "") or args.get("server_id", "") or ""),
            str(args.get("toolName", "") or args.get("tool_name", "") or ""),
            dict(args.get("arguments", {}) or {}),
        ),
        "desktop_os.status": lambda args: _load_adapter("desktop_os_status")(),
        "desktop_os.permissions": lambda args: _load_adapter("desktop_os_permissions")(),
        "desktop_os.open_permission_settings": lambda args: _load_adapter("desktop_os_open_permission_settings")(
            str(args.get("permission", "") or "privacy"),
        ),
        "desktop_os.processes": lambda args: _load_adapter("desktop_os_processes")(
            str(args.get("query", "") or ""),
            _as_int(args.get("limit"), 20),
        ),
        "desktop_os.active_window": lambda args: _load_adapter("desktop_os_active_window")(),
        "save_whatsapp_contact": lambda args: _load_adapter("save_whatsapp_contact")(
            str(args.get("display_name", "") or ""),
            str(args.get("phone_number", "") or ""),
            str(args.get("aliases", "") or ""),
        ),
        "email_draft": lambda args: _load_adapter("email_draft")(
            to=list(args.get("to", []) or []),
            subject=str(args.get("subject", "") or ""),
            topic=str(args.get("topic", "") or args.get("query", "") or ""),
            prompt=str(args.get("prompt", "") or ""),
            tone=str(args.get("tone", "") or "professional"),
            _previousResult=dict(args.get("_previousResult", {}) or {}) if isinstance(args.get("_previousResult", {}), dict) else None,
            _previousOutput=str(args.get("_previousOutput", "") or ""),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "email_send": lambda args: _load_adapter("email_send")(
            to=list(args.get("to", []) or []),
            subject=str(args.get("subject", "") or ""),
            body=str(args.get("body", "") or ""),
            connectionId=str(args.get("connectionId", "") or args.get("connection_id", "") or ""),
            cc=list(args.get("cc", []) or []),
            bcc=list(args.get("bcc", []) or []),
            replyTo=str(args.get("replyTo", "") or args.get("reply_to", "") or ""),
            _previousResult=dict(args.get("_previousResult", {}) or {}) if isinstance(args.get("_previousResult", {}), dict) else None,
            _previousOutput=str(args.get("_previousOutput", "") or ""),
            _confirmed=bool(args.get("_confirmed", False)),
        ),
        "save_memory": _save_memory,
        "delete_memory": _delete_memory,
        "clipboard_read": lambda args: _load_adapter("clipboard_read")(str(args.get("query", "") or "")),
        "clipboard_write": lambda args: _load_adapter("clipboard_write")(str(args.get("text", "") or "")),
    }


def run_capability(tool_name: str, args: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any]:
    payload = args if isinstance(args, dict) else {}
    decision = evaluate_tool(tool_name, payload, state)
    if not decision.allowed:
        return {
            "ok": False,
            "tool": tool_name,
            "output": decision.message,
            "error": {"code": decision.code, "message": decision.message},
        }

    readiness = capability_readiness(tool_name, state=state)
    if readiness.get("ready") is False:
        error_code = str(readiness.get("errorCode", "") or "CAPABILITY_UNAVAILABLE")
        if error_code == "UNSUPPORTED_PLATFORM":
            message = "Bu özellik bu işletim sisteminde desteklenmiyor."
        elif error_code == "DEPENDENCY_UNAVAILABLE":
            message = "Bu özellik bu kurulumda hazır değil."
        elif error_code == "OS_PERMISSION_REQUIRED":
            message = _system_permission_message(str(readiness.get("systemPermissionKey", "") or ""))
        else:
            message = "Bu özellik güvenli şekilde başlatılamadı."
        return {
            "ok": False,
            "tool": tool_name,
            "output": message,
            "error": {"code": error_code, "message": message},
            "readiness": readiness,
        }

    handler = _handlers().get(tool_name)
    if handler is None:
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Bu özellik şu anda hazır değil.",
            "error": {"code": "CAPABILITY_UNAVAILABLE", "message": "Bu özellik şu anda hazır değil."},
        }

    try:
        output = handler(payload)
    except CapabilityLoadError as exc:
        return {
            "ok": False,
            "tool": tool_name,
            "output": exc.message,
            "error": {"code": exc.code, "message": exc.message},
            "readiness": readiness,
        }
    except SafeCapabilityError as exc:
        if str(exc.code or "") == "PERMISSION_REQUIRED":
            status = _system_permission_status_for_capability(tool_name)
            if status in {"required", "denied"}:
                message = _system_permission_message(_CAPABILITY_SYSTEM_PERMISSION_KEYS.get(str(tool_name or "").strip(), ""))
                return {
                    "ok": False,
                    "tool": tool_name,
                    "output": message,
                    "error": {"code": "OS_PERMISSION_REQUIRED", "message": message},
                }
        return {
            "ok": False,
            "tool": tool_name,
            "output": exc.message,
            "error": {"code": exc.code, "message": exc.message},
            "readiness": readiness,
        }
    except ModuleNotFoundError:
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Bu özellik bu kurulumda hazır değil.",
            "error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "Bu özellik bu kurulumda hazır değil."},
            "readiness": readiness,
        }
    except ImportError:
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Bu özellik güvenli şekilde başlatılamadı.",
            "error": {"code": "CAPABILITY_UNAVAILABLE", "message": "Bu özellik güvenli şekilde başlatılamadı."},
            "readiness": readiness,
        }
    except NotImplementedError:
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Bu özellik bu işletim sisteminde desteklenmiyor.",
            "error": {
                "code": "UNSUPPORTED_PLATFORM",
                "message": "Bu özellik bu işletim sisteminde desteklenmiyor.",
            },
            "readiness": readiness,
        }
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "").strip()
        message = str(getattr(exc, "message", "") or "").strip()
        if code and message:
            return {
                "ok": False,
                "tool": tool_name,
                "output": message,
                "error": {"code": code, "message": message},
                "readiness": readiness,
            }
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Araç güvenli şekilde tamamlanamadı.",
            "error": {"code": "TOOL_EXECUTION_FAILED", "message": "Araç güvenli şekilde tamamlanamadı."},
            "readiness": readiness,
        }

    structured_result: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = []
    if isinstance(output, dict):
        structured_candidate = output.get("result")
        if isinstance(structured_candidate, dict):
            structured_result = structured_candidate
        artifact_candidate = output.get("artifacts")
        if isinstance(artifact_candidate, list):
            artifacts = [dict(item) for item in artifact_candidate if isinstance(item, dict)]
        text = (
            str(output.get("text", "") or output.get("output", "") or "").strip()
            or "İşlem tamamlandı."
        )
    else:
        text = str(output or "").strip() or "İşlem tamamlandı."
    return {
        "ok": True,
        "tool": tool_name,
        "output": text,
        "result": structured_result,
        "artifacts": artifacts,
        "error": None,
        "readiness": readiness,
    }


def safe_tool_event(tool_name: str, result: dict[str, Any], *, source: str) -> dict[str, Any]:
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    output = str(result.get("output") or error.get("message") or "").strip()
    return {
        "tool": tool_name,
        "source": source,
        "ok": bool(result.get("ok")),
        "output": output[:1000],
        "errorCode": str(error.get("code", "") or ""),
    }


def run_capability_text(tool_name: str, args: dict[str, Any] | None, state: dict[str, Any]) -> str:
    result = run_capability(tool_name, args, state)
    if result.get("ok"):
        return str(result.get("output", "") or "İşlem tamamlandı.")
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    return str(error.get("message") or result.get("output") or "Araç güvenli şekilde tamamlanamadı.")
