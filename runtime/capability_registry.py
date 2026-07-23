from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import json
import os
import shutil
import sys
from typing import Any, Callable

from runtime import capability_spec
from runtime.execution_trust import consume_grant_for_call, finish_grant_for_call

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
    approval_permission: str
    idempotency: str

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
            "approvalPermission": self.approval_permission,
            "idempotency": self.idempotency,
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
    *,
    usage: str = "",
    examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Yetenek bildirimi. Skill-benzeri kendini-belgeleyen metadata: her
    argümanın `description`'ı (properties içinde), `usage` (ne zaman kullan),
    `examples` (örnek çağrılar). Bunlar planlayıcıya (tool_catalog üzerinden)
    gider → doğru yetenek, doğru argümanla seçilir."""
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
    if usage:
        payload["usage"] = usage
    if examples:
        payload["examples"] = examples
    return payload


TOOL_DECLARATIONS: list[dict[str, Any]] = [
    _tool_decl(
        "open_app",
        "Yerel bir masaüstü uygulamasını açar (Safari, Chrome, Notlar, Spotify…).",
        {
            "app_name": {
                "type": "STRING",
                "description": "Uygulamanın TAM adı, eksiz: 'Google Chrome', 'Safari', 'Notes'. Türkçe ekleri ('Chrome'u') çıkar.",
            }
        },
        ["app_name"],
        usage="Kullanıcı bir uygulamayı açmak istediğinde. URL/arama için browser_control, medya için play_media kullan.",
        examples=[
            {"args": {"app_name": "Google Chrome"}},
            {"args": {"app_name": "Notes"}},
        ],
    ),
    _tool_decl(
        "close_app",
        "Çalışan bir masaüstü uygulamasını kapatır.",
        {
            "app_name": {
                "type": "STRING",
                "description": "Kapatılacak uygulamanın tam adı, eksiz: 'Google Chrome', 'Spotify'.",
            }
        },
        ["app_name"],
        usage="Kullanıcı bir uygulamayı kapatmak istediğinde.",
        examples=[{"args": {"app_name": "Spotify"}}],
    ),
    _tool_decl(
        "sys_info",
        "Sistem bilgisi alır: pil, CPU, RAM, disk, saat, tarih, ağ.",
        {"query": {"type": "STRING", "description": "Hangi bilgi: 'pil', 'saat', 'disk', 'ram', 'ağ' vb."}},
        ["query"],
        usage="Bilgisayarın anlık durumunu/saati sorulduğunda. Çalışan uygulamalar için desktop_os.processes.",
        examples=[{"args": {"query": "pil durumu"}}],
    ),
    _tool_decl(
        "get_weather",
        "Anlık hava durumunu özetler.",
        {"location": {"type": "STRING", "description": "Şehir/konum adı, örn. 'İstanbul'. Boşsa mevcut konum."}},
        usage="Hava durumu sorulduğunda.",
        examples=[{"args": {"location": "Ankara"}}],
    ),
    _tool_decl(
        "get_calendar_events",
        "Apple Calendar takvimini okur (etkinlikleri listeler).",
        {
            "query": {"type": "STRING", "description": "Aranan aralık/konu, örn. 'bu hafta', 'yarın', 'toplantı'."},
            "limit": {"type": "NUMBER", "description": "Döndürülecek en fazla etkinlik sayısı."},
        },
        ["query"],
        usage="Kullanıcı takvimini/programını sorduğunda. Yeni etkinlik için add_calendar_event.",
        examples=[{"args": {"query": "bu hafta", "limit": 10}}],
    ),
    _tool_decl(
        "add_calendar_event",
        "Apple Calendar takvimine yeni etkinlik ekler.",
        {
            "title": {"type": "STRING", "description": "Etkinlik başlığı."},
            "start_iso": {"type": "STRING", "description": "Başlangıç, ISO 8601 yerel saat: 'YYYY-MM-DDTHH:MM:SS'. Göreli ifadeyi ('yarın 14:00') mutlak tarihe çevir."},
            "end_iso": {"type": "STRING", "description": "Bitiş, ISO 8601. Boşsa başlangıçtan 1 saat sonrası."},
            "location": {"type": "STRING", "description": "Konum (varsa)."},
            "notes": {"type": "STRING", "description": "Ek not."},
            "calendar_name": {"type": "STRING", "description": "Hedef takvim adı (varsa)."},
            "all_day": {"type": "BOOLEAN", "description": "Tüm gün etkinliği."},
        },
        ["title", "start_iso"],
        usage="Takvime etkinlik eklerken. Tarihi HER ZAMAN mutlak ISO'ya çevir; belirsizse netleştir.",
        examples=[{"args": {"title": "Diş randevusu", "start_iso": "2026-07-15T09:30:00"}}],
    ),
    _tool_decl(
        "delete_calendar_event",
        "Apple Calendar takviminden etkinlik siler (geri alınamaz — onay gerekir).",
        {
            "title": {"type": "STRING", "description": "Silinecek etkinliğin başlığı."},
            "start_iso": {"type": "STRING", "description": "Etkinliğin başlangıcı (ISO) — doğru eşleşme için."},
            "calendar_name": {"type": "STRING", "description": "Takvim adı (varsa)."},
            "delete_all_matches": {"type": "BOOLEAN", "description": "Aynı başlıklı tüm etkinlikleri sil."},
        },
        ["title"],
        usage="Etkinlik silmek için. Yanlış silmemek için start_iso ile daralt.",
    ),
    _tool_decl(
        "get_reminders",
        "Apple Reminders listesini okur.",
        {
            "query": {"type": "STRING", "description": "Aranan konu/liste, örn. 'bugün', 'alışveriş'."},
            "limit": {"type": "NUMBER", "description": "En fazla öğe sayısı."},
            "list_name": {"type": "STRING", "description": "Belirli liste adı (varsa)."},
        },
        ["query"],
        usage="Hatırlatıcıları/yapılacakları görüntülerken. Yeni öğe için add_reminder.",
    ),
    _tool_decl(
        "add_reminder",
        "Apple Reminders'a yeni hatırlatıcı ekler.",
        {
            "title": {"type": "STRING", "description": "Hatırlatıcı metni."},
            "due_iso": {"type": "STRING", "description": "Son tarih, ISO 8601: 'YYYY-MM-DDTHH:MM:SS'. Göreli ifadeyi mutlaka çevir."},
            "notes": {"type": "STRING", "description": "Ek not."},
            "list_name": {"type": "STRING", "description": "Hedef liste adı (varsa)."},
            "priority": {"type": "STRING", "description": "Öncelik: 'low', 'medium', 'high'."},
            "all_day": {"type": "BOOLEAN", "description": "Saatsiz, gün bazlı."},
        },
        ["title"],
        usage="Hatırlatıcı/yapılacak eklerken. Tarih varsa mutlak ISO'ya çevir.",
        examples=[{"args": {"title": "Faturayı öde", "due_iso": "2026-07-13T18:00:00", "priority": "high"}}],
    ),
    _tool_decl(
        "browser_control",
        "Tarayıcıda bir URL açar, web araması yapar, YouTube'da video açar veya yeni sekme açar.",
        {
            "action": {
                "type": "STRING",
                "description": "İşlem türü: 'open_url' (belirli adres), 'search' (web araması), 'play_youtube' (YouTube video), 'new_tab' (yeni boş sekme — ARAMA DEĞİLDİR).",
            },
            "url": {"type": "STRING", "description": "action='open_url' için açılacak tam adres (https://…)."},
            "query": {"type": "STRING", "description": "action='search'/'play_youtube' için arama metni."},
            "browser": {"type": "STRING", "description": "action='new_tab' için tarayıcı adı (chrome/safari/brave/edge; boşsa Chrome)."},
        },
        ["action"],
        usage="Web adresi açma/arama/YouTube/yeni sekme için. 'Yeni sekme aç' isteği action='new_tab'tır — 'yeni sekme' metnini ASLA aramaya çevirme. Uygulamanın kendisini açmak için open_app kullan.",
        examples=[
            {"args": {"action": "open_url", "url": "https://github.com"}},
            {"args": {"action": "search", "query": "hava durumu istanbul"}},
            {"args": {"action": "play_youtube", "query": "lo-fi çalışma müziği"}},
            {"args": {"action": "new_tab", "browser": "chrome"}},
        ],
    ),
    _tool_decl(
        "web_research",
        "Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
        {
            "query": {"type": "STRING", "description": "Araştırılacak konu/soru — net ve odaklı tut."},
            "max_results": {"type": "NUMBER", "description": "Taranacak kaynak sayısı (varsayılan ~5)."},
            "language_hint": {"type": "STRING", "description": "Tercih edilen kaynak dili, örn. 'tr' veya 'en'."},
        },
        ["query"],
        usage="Güncel/dış bilgi gerektiğinde. Sonucu bir belgeye yazmak için ardından document_write ekle (dependsOn ile).",
        examples=[{"args": {"query": "2025 elektrikli araç pazar payı", "language_hint": "tr"}}],
    ),
    _tool_decl(
        "shell_run",
        "Yerel terminal komutu çalıştırır (güçlü — açık onay gerekir).",
        {
            "command": {"type": "STRING", "description": "Çalıştırılacak tam komut. Yıkıcı/geri alınamaz komutlardan kaçın."},
            "mode": {"type": "STRING", "description": "Yürütme modu (varsa)."},
            "timeout": {"type": "NUMBER", "description": "Saniye cinsinden zaman aşımı."},
            "use_shell": {"type": "BOOLEAN", "description": "Kabuk (shell) üzerinden çalıştır."},
            "working_dir": {"type": "STRING", "description": "Çalışma dizini."},
            "riskOverride": {"type": "STRING", "description": "Risk onayı geçişi (yalnız gerekli olduğunda)."},
        },
        ["command"],
        usage="Yalnız başka yetenek yokken. Dosya işlemleri için file_* , git için git_* yeteneklerini tercih et.",
    ),
    _tool_decl(
        "play_media",
        "YouTube, Spotify veya Apple Music ile şarkı/çalma listesi oynatır.",
        {
            "query": {"type": "STRING", "description": "Çalınacak şarkı, sanatçı veya çalma listesi adı."},
            "provider": {"type": "STRING", "description": "Kaynak: 'youtube', 'spotify' veya 'music'. Belirtilmezse akıllı seçilir."},
            "autoplay": {"type": "BOOLEAN", "description": "Bulunan ilk sonucu otomatik çal (varsayılan true)."},
        },
        ["query"],
        usage="Müzik/video çalmak için. Sadece uygulamayı açmak için open_app kullan.",
        examples=[{"args": {"query": "Tarkan Kuzu Kuzu", "provider": "spotify"}}],
    ),
    _tool_decl(
        "analyze_screen",
        "Aktif ekranda ne olduğunu analiz eder (ne görünüyor sorusu).",
        {
            "query": {"type": "STRING", "description": "Ekran hakkında sorulan soru."},
            "target": {"type": "STRING", "description": "Odaklanılacak bölge/öğe (varsa)."},
        },
        ["query"],
        usage="'Ekranımda ne var / bu ne' gibi sorularda. Ekranda tıklama/yazma için desktop_operator.run.",
    ),
    _tool_decl(
        "desktop_operator.observe_screen",
        "Aktif pencereyi yapılandırılmış ekran gözlemine çevirir (operator alt-adımı).",
        {
            "query": {"type": "STRING", "description": "Gözlem odağı."},
            "target": {"type": "STRING", "description": "Hedef bölge/öğe."},
            "preserveScreenshot": {"type": "BOOLEAN", "description": "Ekran görüntüsünü sakla."},
        },
        usage="İleri ekran otomasyonu alt-adımı. Uçtan uca UI görevi için desktop_operator.run tercih et.",
    ),
    _tool_decl(
        "desktop_operator.locate",
        "Metin veya öğe tipine göre ekrandaki hedef öğeyi bulur (operator alt-adımı).",
        {
            "text": {"type": "STRING", "description": "Aranan görünür metin."},
            "elementType": {"type": "STRING", "description": "Öğe tipi, örn. 'button', 'field'."},
        },
        usage="İleri ekran otomasyonu alt-adımı; genelde desktop_operator.run içinde.",
    ),
    _tool_decl(
        "desktop_operator.focus_window",
        "Bir masaüstü uygulamasını öne alır.",
        {
            "appName": {"type": "STRING", "description": "Öne alınacak uygulama adı."},
            "bundleId": {"type": "STRING", "description": "Uygulama bundle kimliği (varsa)."},
        },
        usage="Bir uygulamayı öne getirmek için. Uygulamayı açmak için open_app.",
    ),
    _tool_decl(
        "desktop_operator.execute_action",
        "Ekranda tek bir güvenli UI eylemi çalıştırır (tıkla/yaz/tuş) — operator alt-adımı.",
        {
            "actionType": {"type": "STRING", "description": "Eylem: 'click', 'type', 'key', 'scroll' vb."},
            "targetText": {"type": "STRING", "description": "Hedef öğenin görünür metni."},
            "elementType": {"type": "STRING", "description": "Öğe tipi."},
            "bbox": {"type": "OBJECT", "description": "Hedef sınır kutusu (varsa)."},
            "text": {"type": "STRING", "description": "actionType='type' için yazılacak metin."},
            "keys": {"type": "ARRAY", "description": "actionType='key' için tuşlar."},
            "delta": {"type": "NUMBER", "description": "Kaydırma miktarı."},
            "duration": {"type": "NUMBER", "description": "Süre (sn)."},
            "appName": {"type": "STRING", "description": "Hedef uygulama."},
        },
        ["actionType"],
        usage="Tek UI eylemi için. Çok adımlı hedef için desktop_operator.run (kendi döngüsünü yürütür).",
    ),
    _tool_decl(
        "desktop_operator.run",
        "Gözlemle→bul→uygula→doğrula döngüsüyle uçtan uca ekran otomasyonu görevi çalıştırır.",
        {
            "goal": {"type": "STRING", "description": "Ulaşılacak hedef, doğal dille, örn. 'Ayarlar'da bildirimleri kapat'."},
            "action": {"type": "STRING", "description": "Tek eylem kısayolu (varsa)."},
            "targetText": {"type": "STRING", "description": "Hedef öğe metni (varsa)."},
            "elementType": {"type": "STRING", "description": "Öğe tipi (varsa)."},
            "text": {"type": "STRING", "description": "Yazılacak metin (varsa)."},
            "appName": {"type": "STRING", "description": "Hedef uygulama."},
            "steps": {"type": "ARRAY", "description": "Elle verilen adımlar (varsa)."},
        },
        usage="YALNIZ yerel (native) uygulama arayüzlerinde tıklama/yazma gerektiren işler için; macOS Ekran Kaydı + Erişilebilirlik izni ister. Web sitesi/tarayıcı işleri için HER ZAMAN browser_agent.run kullan (izin istemez, daha güvenilir).",
        examples=[{"args": {"goal": "System Settings'te karanlık modu aç", "appName": "System Settings"}}],
    ),
    _tool_decl(
        "desktop_operator.cancel",
        "Aktif ekran otomasyonu çalışmasını güvenli şekilde durdurur.",
        {
            "runId": {"type": "STRING", "description": "Durdurulacak çalışma kimliği (varsa)."},
            "reason": {"type": "STRING", "description": "İptal nedeni."},
            "source": {"type": "STRING", "description": "İptali başlatan kaynak."},
        },
        usage="Takılan/istenmeyen bir operator çalışmasını durdurmak için.",
    ),
    _tool_decl(
        "get_youtube_channel_report",
        "YouTube kanal istatistiklerini ve son video performansını raporlar.",
        {
            "query": {"type": "STRING", "description": "Kanal adı/araması."},
            "handle": {"type": "STRING", "description": "Kanal @handle'ı (varsa)."},
            "video_limit": {"type": "NUMBER", "description": "Raporlanacak son video sayısı."},
        },
        usage="Bir YouTube kanalının performansını özetlerken.",
    ),
    _tool_decl(
        "send_whatsapp_message",
        "WhatsApp Desktop/Web üzerinden mesaj hazırlar veya gönderir (gönderim dışa dönük — onay gerekir).",
        {
            "recipient_name": {"type": "STRING", "description": "Alıcının kayıtlı adı. Numarası yoksa kişi rehberinden çözülür."},
            "phone_number": {"type": "STRING", "description": "Uluslararası numara (+90…). recipient_name yeterliyse boş bırak."},
            "message": {"type": "STRING", "description": "Gönderilecek mesaj metni."},
            "app_target": {"type": "STRING", "description": "Hedef: 'desktop' veya 'web'."},
            "send_now": {"type": "BOOLEAN", "description": "true → hemen gönder; false → yalnız hazırla."},
        },
        ["message"],
        usage="WhatsApp mesajı için. Alıcı belirsiz/numara bilinmiyorsa netleştir, uydurma. Kişi kaydı için save_whatsapp_contact.",
    ),
    _tool_decl(
        "save_whatsapp_contact",
        "WhatsApp kişisini kalıcı kaydeder (sonraki mesajlarda adla çözülür).",
        {
            "display_name": {"type": "STRING", "description": "Kişinin görünen adı."},
            "phone_number": {"type": "STRING", "description": "Uluslararası numara (+90…)."},
            "aliases": {"type": "STRING", "description": "Alternatif adlar, virgüllü (varsa)."},
        },
        ["display_name", "phone_number"],
        usage="Bir kişiyi ilerideki WhatsApp mesajları için kaydetmek üzere.",
    ),
    _tool_decl(
        "email_draft",
        "E-posta taslağı hazırlar (göndermez — kullanıcı onayına sunulur).",
        {
            "to": {"type": "ARRAY", "description": "Alıcı e-posta adresleri listesi. Bilinmiyorsa netleştirme iste, uydurma."},
            "subject": {"type": "STRING", "description": "E-posta konusu."},
            "topic": {"type": "STRING", "description": "İçeriğin kısa konusu (gövde bundan üretilir)."},
            "prompt": {"type": "STRING", "description": "Gövde için ayrıntılı yönlendirme/talimat."},
            "tone": {"type": "STRING", "description": "Üslup: 'resmi', 'samimi', 'kısa' vb."},
        },
        ["to"],
        usage="E-posta yazmak için. Taslak onaydan sonra email_send ile gönderilir. Alıcı belirsizse netleştir.",
        examples=[{"args": {"to": ["ali@ornek.com"], "subject": "Toplantı", "topic": "cuma 14:00 toplantı daveti", "tone": "resmi"}}],
    ),
    _tool_decl(
        "email_send",
        "Onaylı e-postayı GÖNDERİR (geri alınamaz — açık onay gerekir).",
        {
            "to": {"type": "ARRAY", "description": "Alıcı adresleri. Gerçek adres yoksa gönderme, netleştir."},
            "subject": {"type": "STRING", "description": "Konu."},
            "body": {"type": "STRING", "description": "Gövde (tam metin)."},
            "connectionId": {"type": "STRING", "description": "Gönderen hesap bağlantı kimliği (varsa)."},
            "cc": {"type": "ARRAY", "description": "CC adresleri."},
            "bcc": {"type": "ARRAY", "description": "BCC adresleri."},
            "replyTo": {"type": "STRING", "description": "Yanıt adresi."},
        },
        ["to", "subject", "body"],
        usage="Genelde email_draft ile taslak hazırlanıp onaydan sonra gönderilir. Doğrudan gönderim geri alınamaz.",
    ),
    _tool_decl(
        "document_read",
        "Zengin belge içeriğini (Word/PDF/metin) okur ve özetlenebilir metne çevirir.",
        {
            "path": {"type": "STRING", "description": "Okunacak belgenin tam yolu (.docx/.pdf/.txt…)."},
            "text": {"type": "STRING", "description": "Doğrudan metin verilecekse (path yerine)."},
            "mode": {"type": "STRING", "description": "Okuma modu (varsa)."},
        },
        ["path"],
        usage="Word/PDF gibi belgeleri okurken. Görüntüdeki metin için ocr_read, düz metin/kod için file_read.",
    ),
    _tool_decl(
        "ocr_read",
        "Görsel veya taranmış PDF sayfasındaki metni OCR ile çıkarır.",
        {
            "path": {"type": "STRING", "description": "Görsel/PDF yolu."},
            "mode": {"type": "STRING", "description": "OCR modu (varsa)."},
            "languageHint": {"type": "STRING", "description": "Metin dili ipucu, örn. 'tr'."},
        },
        ["path"],
        usage="Fotoğraf/ekran görüntüsü/taranmış belgedeki YAZIYI okumak için. Seçilebilir metinli belge için document_read.",
    ),
    _tool_decl(
        "image_read",
        "Yerel bir görselin ne içerdiğini inceler (açıklama/etiket/renk).",
        {
            "path": {"type": "STRING", "description": "İncelenecek görsel yolu."},
            "mode": {"type": "STRING", "description": "'summary' (açıklama), 'metadata' veya 'palette' (renkler)."},
        },
        ["path"],
        usage="Bir görselin İÇERİĞİNİ anlamak için. İçindeki yazıyı okumak için ocr_read.",
    ),
    _tool_decl(
        "image_generate",
        "Metin isteminden Gemini ile yüksek kaliteli görsel üretir ve dosyaya kaydeder.",
        {
            "prompt": {"type": "STRING", "description": "Üretilecek görselin ayrıntılı tarifi."},
            "outputPath": {"type": "STRING", "description": "Kaydedilecek yol (verilmezse akıllı seçilir)."},
            "title": {"type": "STRING", "description": "Görsel başlığı/dosya adı."},
            "aspectRatio": {"type": "STRING", "description": "En-boy oranı, örn. '1:1', '16:9' veya '9:16'."},
            "imageSize": {"type": "STRING", "description": "Çözünürlük: '1K', '2K' veya açık istekle '4K'."},
            "overwrite": {"type": "BOOLEAN", "description": "Üzerine yaz."},
        },
        ["prompt"],
        usage="Sıfırdan görsel/illüstrasyon üretmek için. Web'den hazır görsel indirmek için image_fetch.",
        examples=[{"args": {"prompt": "minimalist dağ manzarası, düz renkler", "aspectRatio": "1:1", "imageSize": "2K"}}],
    ),
    _tool_decl(
        "image_edit",
        "Kullanıcının seçtiği yerel görseli Gemini ile isteğe uygun şekilde düzenler ve yeni dosya oluşturur.",
        {
            "prompt": {"type": "STRING", "description": "Görsele uygulanacak değişiklik; kullanıcı isteği aynen korunur."},
            "sourcePath": {"type": "STRING", "description": "Düzenlenecek ana görsel yolu."},
            "sourcePaths": {"type": "ARRAY", "description": "İsteğe bağlı ek referans görsel yolları."},
            "outputPath": {"type": "STRING", "description": "Yeni görselin kaydedileceği yol."},
            "title": {"type": "STRING", "description": "Çıktı başlığı/dosya adı."},
            "aspectRatio": {"type": "STRING", "description": "Çıktı en-boy oranı."},
            "imageSize": {"type": "STRING", "description": "Çözünürlük: '1K', '2K' veya '4K'."},
            "overwrite": {"type": "BOOLEAN", "description": "Üzerine yaz."},
        },
        ["prompt", "sourcePath"],
        usage="Seçili/yüklenmiş görselde öğe ekleme, kaldırma, arka plan veya stil değiştirme için. Yalnız inceleme için image_read.",
        examples=[{"args": {"prompt": "Arka planı gün batımı yap, kişiyi değiştirme", "sourcePath": "portrait.png", "imageSize": "2K"}}],
    ),
    _tool_decl(
        "image_fetch",
        "Herkese açık bir kaynaktan (Openverse/Wikimedia) bir konu için görsel indirir ve kullanıcının klasörüne (varsayılan masaüstü) kaydeder.",
        {
            "query": {"type": "STRING", "description": "İndirilecek görselin konusu/araması."},
            "destination": {"type": "STRING", "description": "Kaydedilecek klasör (varsayılan masaüstü)."},
            "count": {"type": "INTEGER", "description": "İndirilecek görsel sayısı."},
            "overwrite": {"type": "BOOLEAN", "description": "Var olanın üzerine yaz."},
        },
        ["query"],
        usage="Web'den hazır/telifsiz görsel indirmek için. Sıfırdan görsel üretmek için image_generate.",
    ),
    _tool_decl(
        "file_read",
        "Bir metin/kod dosyasını güvenli şekilde okur (isteğe bağlı satır aralığı).",
        {
            "path": {"type": "STRING", "description": "Okunacak dosyanın tam yolu."},
            "max_bytes": {"type": "INTEGER", "description": "En fazla okunacak bayt (büyük dosyalar için)."},
            "start_line": {"type": "INTEGER", "description": "Başlangıç satırı (1'den)."},
            "end_line": {"type": "INTEGER", "description": "Bitiş satırı (dahil)."},
        },
        ["path"],
        usage="Belge/kod dosyası içeriğini görmek için. Word/PDF gibi zengin belgeler için document_read kullan.",
        examples=[{"args": {"path": "/Users/x/Desktop/notlar.txt"}}],
    ),
    _tool_decl(
        "file_search",
        "Bir klasör ağacında dosya İÇERİĞİNDE metin/regex arar (ripgrep destekli).",
        {
            "query": {"type": "STRING", "description": "Aranacak metin veya regex deseni."},
            "path": {"type": "STRING", "description": "Arama kök klasörü (boşsa proje/çalışma dizini)."},
            "glob": {"type": "STRING", "description": "Dosya filtresi, örn. '*.py'."},
            "regex": {"type": "BOOLEAN", "description": "query'yi regex olarak yorumla."},
            "case_sensitive": {"type": "BOOLEAN", "description": "Büyük/küçük harf duyarlı."},
            "max_results": {"type": "INTEGER", "description": "En fazla eşleşme."},
        },
        ["query"],
        usage="Dosya içinde metin ararken. Dosya ADIYLA bulmak veya klasör yapısı için directory_tree.",
        examples=[{"args": {"query": "TODO", "glob": "*.py"}}],
    ),
    _tool_decl(
        "directory_tree",
        "Proje/klasör yapısını (ağaç) çıkarır; gürültülü klasörleri atlar.",
        {
            "path": {"type": "STRING", "description": "Kök klasör (boşsa çalışma dizini)."},
            "max_depth": {"type": "INTEGER", "description": "En fazla derinlik."},
            "max_entries": {"type": "INTEGER", "description": "En fazla girdi sayısı."},
        },
        usage="Bir klasörde neler olduğunu/proje yapısını görmek için. Dosya içeriğinde arama için file_search.",
    ),
    _tool_decl(
        "git_status",
        "Bir git deposunun durumunu (branch + staged/unstaged/untracked) döndürür.",
        {"path": {"type": "STRING", "description": "Depo yolu (boşsa çalışma dizini)."}},
        usage="Bir repoda hangi değişiklikler var diye bakarken.",
    ),
    _tool_decl(
        "git_diff",
        "Bir git deposundaki çalışma ağacı veya staged farkını (diff) döndürür.",
        {
            "path": {"type": "STRING", "description": "Depo yolu."},
            "staged": {"type": "BOOLEAN", "description": "true → staged (index) farkı; false → çalışma ağacı."},
            "target_file": {"type": "STRING", "description": "Yalnız bu dosyanın farkı (varsa)."},
        },
        usage="Kod değişikliklerinin detayını görmek için.",
    ),
    _tool_decl(
        "file_write",
        "Bir metin/kod dosyası oluşturur veya (overwrite=true ile) üzerine yazar.",
        {
            "path": {"type": "STRING", "description": "Yazılacak dosyanın tam yolu."},
            "content": {"type": "STRING", "description": "Dosyaya yazılacak tam içerik."},
            "overwrite": {"type": "BOOLEAN", "description": "Var olan dosyanın üzerine yaz (yoksa hata verir)."},
        },
        ["path"],
        usage="Düz metin/kod dosyası oluştururken. Word belgesi için document_write, tablo için spreadsheet_write.",
    ),
    _tool_decl(
        "file_patch",
        "Var olan bir dosyada çıpalı bul/değiştir uygular (old_string → new_string).",
        {
            "path": {"type": "STRING", "description": "Düzenlenecek dosyanın tam yolu."},
            "old_string": {"type": "STRING", "description": "Değiştirilecek TAM mevcut metin (benzersiz olmalı)."},
            "new_string": {"type": "STRING", "description": "Yerine yazılacak yeni metin."},
            "replace_all": {"type": "BOOLEAN", "description": "Tüm eşleşmeleri değiştir."},
        },
        ["path", "old_string"],
        usage="Bir dosyanın küçük bir bölümünü değiştirmek için. Tüm dosyayı yeniden yazmak için file_write.",
    ),
    _tool_decl(
        "git_commit",
        "Değişiklikleri commit'ler (opsiyonel git add -A). PUSH YAPMAZ.",
        {
            "path": {"type": "STRING", "description": "Depo yolu."},
            "message": {"type": "STRING", "description": "Commit mesajı — kısa ve açıklayıcı."},
            "add_all": {"type": "BOOLEAN", "description": "Commit'ten önce tüm değişiklikleri sahnele (git add -A)."},
        },
        ["message"],
        usage="Değişiklikleri kaydederken. Push YAPMAZ (güvenlik). Yeni dal için git_branch.",
    ),
    _tool_decl(
        "git_branch",
        "Yeni bir git branch'i oluşturur (varsayılan: oluşturup geçer).",
        {
            "path": {"type": "STRING", "description": "Depo yolu."},
            "name": {"type": "STRING", "description": "Yeni dal adı."},
            "checkout": {"type": "BOOLEAN", "description": "Oluşturduktan sonra dala geç (varsayılan true)."},
        },
        ["name"],
        usage="Ana dalda çalışmadan önce yeni bir dal açarken.",
    ),
    _tool_decl(
        "canvas_write",
        "Metin, tablo, grafik ve görselleri PDF veya PNG canvas çıktısına dönüştürür.",
        {
            "prompt": {"type": "STRING", "description": "İçerik/düzen için talimat."},
            "outputPath": {"type": "STRING", "description": "Kaydedilecek çıktı yolu."},
            "title": {"type": "STRING", "description": "Sayfa başlığı."},
            "blocks": {"type": "ARRAY", "description": "Yerleştirilecek içerik blokları (varsa)."},
            "sections": {"type": "ARRAY", "description": "Bölümler (varsa)."},
            "outputFormat": {"type": "STRING", "description": "Çıktı biçimi: 'pdf' veya 'png'."},
            "width": {"type": "NUMBER", "description": "Genişlik (px)."},
            "height": {"type": "NUMBER", "description": "Yükseklik (px)."},
            "sourceContext": {"type": "STRING", "description": "Ek bağlam metni."},
            "sourcePath": {"type": "STRING", "description": "Kaynak dosya (varsa)."},
            "overwrite": {"type": "BOOLEAN", "description": "Üzerine yaz."},
        },
        ["outputPath"],
        usage="Metin+tablo+grafik+görseli tek görsel sayfada (PDF/PNG) birleştirmek için. Sadece Word için document_write.",
    ),
    _tool_decl(
        "data_analyze",
        "CSV, JSON veya Excel verisini yerel olarak analiz eder (özet/profil/önizleme).",
        {
            "path": {"type": "STRING", "description": "Veri dosyası yolu (.csv/.json/.xlsx/.xls)."},
            "mode": {"type": "STRING", "description": "'summary', 'profile' veya 'preview'."},
            "columns": {"type": "ARRAY", "description": "Odaklanılacak sütun adları (varsa)."},
        },
        ["path"],
        usage="Bir veri dosyasını anlamak/özetlemek için. Grafik çizmek için chart_generate.",
    ),
    _tool_decl(
        "chart_generate",
        "CSV, JSON veya Excel verisinden yerel PNG grafik üretir.",
        {
            "path": {"type": "STRING", "description": "Veri dosyası yolu."},
            "chartType": {"type": "STRING", "description": "Tür: 'bar', 'line', 'scatter' veya 'histogram'."},
            "xColumn": {"type": "STRING", "description": "X ekseni sütunu."},
            "yColumn": {"type": "STRING", "description": "Y ekseni sütunu."},
            "title": {"type": "STRING", "description": "Grafik başlığı."},
            "outputPath": {"type": "STRING", "description": "Grafiğin kaydedileceği PNG yolu."},
        },
        ["path"],
        usage="Veriyi görselleştirmek için. Önce veriyi anlamak istersen data_analyze.",
        examples=[{"args": {"path": "/Users/x/veri.csv", "chartType": "bar", "xColumn": "ay", "yColumn": "gelir"}}],
    ),
    _tool_decl(
        "math_solve",
        "Matematik ifadesini yerel olarak çözer veya sadeleştirir.",
        {
            "expression": {"type": "STRING", "description": "Çözülecek ifade/denklem, örn. '2x+3=7' veya 'integral x^2 dx'."},
            "mode": {"type": "STRING", "description": "İşlem türü (çöz/sadeleştir) — varsayılan otomatik."},
        },
        ["expression"],
        usage="Hesaplama/denklem/türev-integral için. LaTeX girdiyi ayrıştırmak için latex_parse.",
        examples=[{"args": {"expression": "12 * (3 + 4)"}}],
    ),
    _tool_decl(
        "latex_parse",
        "LaTeX matematik ifadesini yerel sembolik forma çevirir/normalize eder.",
        {
            "expression": {"type": "STRING", "description": "LaTeX ifadesi, örn. '\\frac{a}{b}'."},
            "mode": {"type": "STRING", "description": "'parse' veya 'normalize'."},
        },
        ["expression"],
        usage="LaTeX'i işlerken. Sayısal çözüm için math_solve.",
    ),
    _tool_decl(
        "quantum_model_problem",
        "Optimizasyon problemini QUBO/Ising demo modeline dönüştürür.",
        {
            "prompt": {"type": "STRING", "description": "Modellemek istenen optimizasyon problemi."},
            "problemClass": {"type": "STRING", "description": "Problem sınıfı (varsa)."},
        },
        ["prompt"],
        usage="Kuantum/optimizasyon demo akışının ilk adımı; ardından quantum_run_experiment.",
    ),
    _tool_decl(
        "quantum_run_experiment",
        "QAOA/VQE simülatör demo deneyini yürütür.",
        {
            "prompt": {"type": "STRING", "description": "Deney tanımı/hedefi."},
            "algorithm": {"type": "STRING", "description": "Algoritma: 'qaoa' veya 'vqe'."},
            "shots": {"type": "NUMBER", "description": "Ölçüm sayısı."},
        },
        ["prompt"],
        usage="Kuantum demo deneyi çalıştırmak için (Qiskit/Aer gerekir).",
    ),
    _tool_decl(
        "quantum_compare_classical",
        "Kuantum demo sonucunu klasik baseline ile karşılaştırır.",
        {"prompt": {"type": "STRING", "description": "Karşılaştırılacak problem/sonuç bağlamı."}},
        ["prompt"],
        usage="Kuantum sonucunu klasik yöntemle kıyaslarken.",
    ),
    _tool_decl(
        "quantum_generate_report",
        "Kuantum deney akışı için teknik rapor ve metrik artifact üretir.",
        {
            "prompt": {"type": "STRING", "description": "Rapor konusu/kapsamı."},
            "title": {"type": "STRING", "description": "Rapor başlığı."},
        },
        ["prompt"],
        usage="Kuantum deney akışının sonunda özet rapor üretmek için.",
    ),
    _tool_decl(
        "document_write",
        "DOCX (Word) belgesi oluşturur veya bir kaynaktan dönüştürür.",
        {
            "prompt": {"type": "STRING", "description": "Belge içeriği için talimat/konu. Önceki adımın çıktısı otomatik bağlam olur."},
            "outputPath": {"type": "STRING", "description": "Kaydedilecek dosya yolu (verilmezse akıllı seçilir)."},
            "title": {"type": "STRING", "description": "Belge başlığı."},
            "sections": {"type": "ARRAY", "description": "Yapılandırılmış bölüm listesi; önceki adım sonucundan şablonla bağlanabilir."},
            "blocks": {"type": "ARRAY", "description": "Metin, tablo, görsel ve grafik blokları."},
            "sourcePath": {"type": "STRING", "description": "Dönüştürülecek kaynak dosya yolu (varsa)."},
            "sourceContext": {"type": "STRING", "description": "Ek bağlam metni."},
            "overwrite": {"type": "BOOLEAN", "description": "Var olan dosyanın üzerine yaz."},
        },
        usage="Rapor/mektup/not gibi Word belgesi üretmek için. Araştırma sonrası kullanılıyorsa web_research adımına dependsOn ver; içerik _previousOutput'tan gelir.",
        examples=[{"args": {"title": "Pazar Raporu", "prompt": "Elektrikli araç pazarı hakkında 1 sayfalık özet"}}],
    ),
    _tool_decl(
        "spreadsheet_write",
        "XLSX (Excel) çalışma sayfası üretir.",
        {
            "prompt": {"type": "STRING", "description": "Tablo içeriği/yapısı için talimat. Önceki adım çıktısı bağlam olur."},
            "outputPath": {"type": "STRING", "description": "Kaydedilecek yol (verilmezse akıllı seçilir)."},
            "title": {"type": "STRING", "description": "Çalışma sayfası başlığı."},
            "columns": {"type": "ARRAY", "description": "Sütun adları; örn. {{steps.analiz.result.columns}}."},
            "rows": {"type": "ARRAY", "description": "Yapılandırılmış satırlar; örn. {{steps.analiz.result.previewRows}}."},
            "sourceContext": {"type": "STRING", "description": "Ek bağlam/veri metni."},
            "overwrite": {"type": "BOOLEAN", "description": "Üzerine yaz."},
        },
        usage="Sayısal/tablosal veri (bütçe, liste, hesap) için. Metin belgesi için document_write.",
        examples=[{"args": {"title": "Aylık Bütçe", "prompt": "Gelir-gider tablosu, 3 aylık"}}],
    ),
    _tool_decl(
        "presentation_write",
        "PPTX (PowerPoint) sunum üretir.",
        {
            "prompt": {"type": "STRING", "description": "Sunum konusu/anahatları için talimat. Önceki adım çıktısı bağlam olur."},
            "outputPath": {"type": "STRING", "description": "Kaydedilecek yol (verilmezse akıllı seçilir)."},
            "title": {"type": "STRING", "description": "Sunum başlığı."},
            "slides": {"type": "ARRAY", "description": "Başlık, gövde ve madde alanları taşıyan yapılandırılmış slayt listesi."},
            "blocks": {"type": "ARRAY", "description": "Tekrarlanabilir görsel içerik blokları."},
            "sourceContext": {"type": "STRING", "description": "Ek bağlam metni."},
            "overwrite": {"type": "BOOLEAN", "description": "Üzerine yaz."},
        },
        usage="Slayt destesi için. Araştırma sonrası kullanılıyorsa web_research'e dependsOn ver.",
        examples=[{"args": {"title": "Ürün Tanıtımı", "prompt": "5 slaytlık ürün sunumu"}}],
    ),
    _tool_decl(
        "retrieve_context",
        "Yerel çalışma alanı ve konuşmalardan bağlam eşleşmeleri döndürür (çevrimdışı).",
        {
            "query": {"type": "STRING", "description": "Aranan konu/soru."},
            "sources": {"type": "STRING", "description": "Kaynaklar, virgüllü: 'workspace,conversations'."},
            "limit": {"type": "NUMBER", "description": "En fazla eşleşme."},
            "conversationId": {"type": "STRING", "description": "Belirli konuşma bağlamı (varsa)."},
        },
        ["query"],
        usage="Yerel/geçmiş bilgi gerektiğinde veya web erişilemediğinde. Güncel dış bilgi için web_research.",
    ),
    _tool_decl(
        "speech_capture",
        "Yerel mikrofondan kısa ses kaydı başlatır veya durdurur.",
        {
            "action": {"type": "STRING", "description": "'start' (kaydı başlat) veya 'stop' (durdur)."},
            "_uiGesture": {"type": "BOOLEAN", "description": "Kullanıcı jestiyle tetiklendi (dahili)."},
        },
        ["action"],
        usage="Sesli not/dikte almak için kaydı başlatıp durdurma. Kaydı metne çevirmek için speech_to_text.",
    ),
    _tool_decl(
        "speech_to_text",
        "Yerel ses kaydını metne çevirir (dikte).",
        {
            "audioPath": {"type": "STRING", "description": "Çevrilecek ses dosyası yolu (varsa)."},
            "sessionId": {"type": "STRING", "description": "Kayıt oturumu kimliği (varsa)."},
            "languageHint": {"type": "STRING", "description": "Konuşma dili ipucu, örn. 'tr'."},
            "taskId": {"type": "STRING", "description": "İlişkili görev kimliği (varsa)."},
        },
        usage="Ses kaydını yazıya dökmek için. Yazıyı sese çevirmek için text_to_speech.",
    ),
    _tool_decl(
        "text_to_speech",
        "Metni yerel olarak sesli okur.",
        {
            "text": {"type": "STRING", "description": "Sesli okunacak metin."},
            "languageHint": {"type": "STRING", "description": "Dil ipucu, örn. 'tr'."},
            "voice": {"type": "STRING", "description": "Ses/tını adı (varsa)."},
            "interrupt": {"type": "BOOLEAN", "description": "Süren okumayı kesip yeniden başla."},
        },
        ["text"],
        usage="Bir metni/cevabı sesli okutmak için.",
    ),
    _tool_decl(
        "mcp_call_tool",
        "Bağlı bir MCP sunucusundaki aracı çağırır (harici entegrasyonlar).",
        {
            "serverId": {"type": "STRING", "description": "MCP sunucu kimliği."},
            "toolName": {"type": "STRING", "description": "Çağrılacak araç adı."},
            "arguments": {"type": "OBJECT", "description": "Araca geçilecek argümanlar (araç şemasına uygun)."},
        },
        ["serverId", "toolName"],
        usage="Yerleşik yeteneklerin karşılamadığı, kullanıcının bağladığı bir MCP aracı gerektiğinde.",
    ),
    _tool_decl(
        "run_skill",
        "Yerel skill manifestinden kontrollü, çok adımlı bir beceri çalıştırır.",
        {
            "skillId": {"type": "STRING", "description": "Çalıştırılacak beceri kimliği (skill kataloğundan)."},
            "payload": {"type": "OBJECT", "description": "Becerinin beklediği girdi alanları."},
        },
        ["skillId"],
        usage="Kullanıcının tanımladığı hazır bir beceri/otomasyon gerektiğinde.",
    ),
    _tool_decl(
        "desktop_os.status",
        "Masaüstü OS yetenek ve native entegrasyon durumunu döndürür.",
        {},
        usage="Masaüstünün hangi yeteneklerinin hazır olduğunu kontrol ederken (tanılama).",
    ),
    _tool_decl(
        "desktop_os.permissions",
        "Masaüstü izin modelini ve izin hazırlık (readiness) durumunu döndürür.",
        {},
        usage="Hangi sistem izinlerinin verildiğini görmek için. İzin ekranını açmak için desktop_os.open_permission_settings.",
    ),
    _tool_decl(
        "desktop_os.open_permission_settings",
        "İlgili sistem izin ekranını güvenli şekilde açar.",
        {"permission": {"type": "STRING", "description": "Açılacak izin türü, örn. 'accessibility', 'screen'."}},
        usage="Bir izin eksikse kullanıcıyı doğru sistem ayar ekranına yönlendirmek için.",
    ),
    _tool_decl(
        "desktop_os.processes",
        "Çalışan uygulamaları/prosesleri güvenli şekilde listeler.",
        {
            "query": {"type": "STRING", "description": "Filtre/arama (varsa)."},
            "limit": {"type": "NUMBER", "description": "En fazla sonuç."},
        },
        usage="Hangi uygulamaların açık olduğunu görmek için. Genel sistem bilgisi için sys_info.",
    ),
    _tool_decl(
        "desktop_os.active_window",
        "Şu an öndeki (aktif) pencere bilgisini döndürür.",
        {},
        usage="Kullanıcının o an hangi uygulamada olduğunu öğrenmek için.",
    ),
    _tool_decl(
        "save_memory",
        "Kullanıcı hakkında kalıcı bir tercih/olgu kaydeder (sonraki oturumlarda hatırlanır).",
        {
            "category": {"type": "STRING", "description": "Kategori, örn. 'tercih', 'kişi', 'proje'."},
            "key": {"type": "STRING", "description": "Kısa anahtar/etiket."},
            "value": {"type": "STRING", "description": "Hatırlanacak bilgi."},
        },
        ["key", "value"],
        usage="Kullanıcı 'bunu hatırla/aklında tut' dediğinde kalıcı tercih/olgu kaydetmek için.",
        examples=[{"args": {"category": "tercih", "key": "kahve", "value": "sütlü, şekersiz"}}],
    ),
    _tool_decl(
        "delete_memory",
        "Kalıcı hafızadan bir kaydı siler.",
        {
            "category": {"type": "STRING", "description": "Kategori (varsa)."},
            "key": {"type": "STRING", "description": "Silinecek kaydın anahtarı."},
            "match_text": {"type": "STRING", "description": "Anahtar yoksa içerikle eşleştir."},
        },
        usage="Kullanıcı 'şunu unut/hatırlama' dediğinde.",
    ),
    _tool_decl(
        "clipboard_read",
        "Panodaki (clipboard) metni okur.",
        {"query": {"type": "STRING", "description": "İsteğe bağlı bağlam/filtre."}},
        usage="Kullanıcı 'panodakini/kopyaladığımı' işleme dediğinde.",
    ),
    _tool_decl(
        "clipboard_write",
        "Verilen metni panoya (clipboard) kopyalar.",
        {"text": {"type": "STRING", "description": "Panoya kopyalanacak metin."}},
        ["text"],
        usage="Bir sonucu/metni kullanıcının yapıştırabilmesi için panoya koymak.",
    ),
]

# Tek Spec mimarisi: göç edilen yetenekler kataloğa spec'ten türetilerek girer.
TOOL_DECLARATIONS.extend(
    capability_spec.tool_declaration(item) for item in capability_spec.SPECS
)


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
    "image_edit": _AdapterSpec("actions.image_edit", "image_edit"),
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

# Tek Spec: göç edilen yetenekler adapter tablosuna spec'ten girer.
for _spec_item in capability_spec.SPECS:
    _ADAPTER_SPECS[_spec_item.name] = _AdapterSpec(_spec_item.module, _spec_item.attribute)


def capability_names() -> set[str]:
    return {str(item["name"]) for item in TOOL_DECLARATIONS}


# Kullanıcıya gösterilen dostane yetenek adları (TR). Ham slug ("document_write")
# yerine "Belge oluşturma" — degrade/kullanılamıyor mesajlarında ve plan
# önizlemesinde kullanılır.
_CAPABILITY_DISPLAY_NAMES: dict[str, str] = {
    "open_app": "Uygulama açma",
    "close_app": "Uygulama kapatma",
    "sys_info": "Sistem bilgisi",
    "shell_run": "Terminal komutu",
    "browser_control": "Tarayıcı kontrolü",
    "play_media": "Medya oynatma",
    "analyze_screen": "Ekran analizi",
    "clipboard_read": "Panoyu okuma",
    "clipboard_write": "Panoya yazma",
    "file_read": "Dosya okuma",
    "file_write": "Dosya yazma",
    "file_patch": "Dosya düzenleme",
    "file_search": "Dosya arama",
    "directory_tree": "Klasör ağacı",
    "git_status": "Git durumu",
    "git_diff": "Git değişiklikleri",
    "git_commit": "Git commit",
    "git_branch": "Git dal",
    "web_research": "Web araştırması",
    "retrieve_context": "Yerel bağlam getirme",
    "document_read": "Belge okuma",
    "ocr_read": "Görüntüden metin (OCR)",
    "image_read": "Görsel inceleme",
    "image_fetch": "Görsel indirme",
    "image_generate": "Görsel üretme",
    "image_edit": "Görsel düzenleme",
    "document_write": "Belge oluşturma",
    "spreadsheet_write": "Tablo oluşturma",
    "presentation_write": "Sunum oluşturma",
    "canvas_write": "Görsel pano oluşturma",
    "chart_generate": "Grafik oluşturma",
    "data_analyze": "Veri analizi",
    "email_draft": "E-posta taslağı",
    "email_send": "E-posta gönderme",
    "send_whatsapp_message": "WhatsApp mesajı",
    "save_whatsapp_contact": "WhatsApp kişi kaydı",
    "add_calendar_event": "Takvim etkinliği ekleme",
    "delete_calendar_event": "Takvim etkinliği silme",
    "get_calendar_events": "Takvim etkinliklerini görme",
    "add_reminder": "Hatırlatıcı ekleme",
    "get_reminders": "Hatırlatıcıları görme",
    "get_weather": "Hava durumu",
    "get_youtube_channel_report": "YouTube kanal raporu",
    "math_solve": "Matematik çözümü",
    "latex_parse": "LaTeX işleme",
    "speech_capture": "Ses kaydı",
    "speech_to_text": "Sesten metne",
    "text_to_speech": "Metinden sese",
    "run_skill": "Beceri çalıştırma",
    "mcp_call_tool": "MCP aracı",
    "save_memory": "Hafızaya kaydetme",
    "delete_memory": "Hafızadan silme",
    "quantum_model_problem": "Kuantum modelleme",
    "quantum_run_experiment": "Kuantum deneyi",
    "quantum_compare_classical": "Kuantum karşılaştırma",
    "quantum_generate_report": "Kuantum raporu",
    "desktop_operator.run": "Ekran otomasyonu",
    "desktop_operator.execute_action": "Ekran eylemi",
    "desktop_operator.focus_window": "Pencere odaklama",
    "desktop_operator.observe_screen": "Ekran gözlemi",
    "desktop_operator.locate": "Ekranda konum bulma",
    "desktop_operator.cancel": "Otomasyonu iptal",
    "desktop_os.status": "Masaüstü durumu",
    "desktop_os.permissions": "İzin durumu",
    "desktop_os.processes": "Çalışan uygulamalar",
    "desktop_os.active_window": "Aktif pencere",
    "desktop_os.open_permission_settings": "İzin ayarlarını açma",
}
for _spec_item in capability_spec.SPECS:
    if _spec_item.display_name:
        _CAPABILITY_DISPLAY_NAMES[_spec_item.name] = _spec_item.display_name


def capability_display_name(name: str) -> str:
    """Yetenek slug'ının kullanıcıya gösterilecek dostane TR adı. Bilinmeyen
    slug için okunabilir bir yedek üretir (alt çizgi/nokta → boşluk, baş harf)."""
    normalized = str(name or "").strip()
    if not normalized:
        return "Bu işlem"
    label = _CAPABILITY_DISPLAY_NAMES.get(normalized)
    if label:
        return label
    readable = normalized.split(".")[-1].replace("_", " ").strip()
    return readable[:1].upper() + readable[1:] if readable else "Bu işlem"


_DARWIN_ONLY_CAPABILITIES = {
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
}
_WRITE_CAPABILITIES = {
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "image_generate",
    "image_edit",
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
    "image_edit",
    "chart_generate",
    "run_skill",
    "mcp_call_tool",
    "file_write",
    "file_patch",
    "git_commit",
    "git_branch",
}
_SIDE_EFFECT_CAPABILITIES.update(
    _spec_item.name for _spec_item in capability_spec.SPECS if _spec_item.side_effect
)
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
_TRUSTED_IDEMPOTENT_WRITE_CAPABILITIES = {
    "clipboard_write",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
}
_APPROVAL_READ_ONLY_CAPABILITIES = {
    "clipboard_read",
    "data_analyze",
    "desktop_os.permissions",
    "desktop_os.status",
    "directory_tree",
    "document_read",
    "email_draft",
    "file_read",
    "file_search",
    "get_calendar_events",
    "get_reminders",
    "get_weather",
    "get_youtube_channel_report",
    "git_diff",
    "git_status",
    "image_read",
    "latex_parse",
    "math_solve",
    "ocr_read",
    "quantum_compare_classical",
    "quantum_generate_report",
    "quantum_model_problem",
    "quantum_run_experiment",
    "retrieve_context",
    "speech_to_text",
    "sys_info",
    "web_research",
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
    "quantum_model_problem": (),
    "quantum_run_experiment": (),
    "quantum_compare_classical": (),
    "quantum_generate_report": (),
}
for _spec_item in capability_spec.SPECS:
    if _spec_item.dependency_keys:
        _CAPABILITY_DEPENDENCY_KEYS[_spec_item.name] = tuple(_spec_item.dependency_keys)


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


def _desktop_os_runtime_recovered(name: str) -> bool:
    if not str(name or "").startswith("desktop_os."):
        return False
    try:
        module = import_module("actions.desktop_os")
        status = module.desktop_os_runtime_status()
        detail = status.get("detail", {}) if isinstance(status, dict) else {}
        detail = detail if isinstance(detail, dict) else {}
        if name == "desktop_os.permissions":
            permissions = module.desktop_os_permissions()
            result = permissions.get("result", {}) if isinstance(permissions, dict) else {}
            return bool(isinstance(result, dict) and result.get("available", False))
        if name == "desktop_os.processes":
            return bool(detail.get("processInspectionAvailable", False))
        if name == "desktop_os.active_window":
            return bool(detail.get("activeWindowAvailable", False))
        return bool(status.get("available", False))
    except Exception:
        return False


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
    dependencies = metadata.get("dependencyKeys", [])
    dependencies = [str(item or "").strip() for item in dependencies if str(item or "").strip()]
    snapshot = dependency_status if isinstance(dependency_status, dict) else dependency_status_snapshot()
    for alias in _runtime_capability_state_aliases(normalized):
        observed = runtime_states.get(alias)
        if isinstance(observed, dict) and (
            observed.get("ready") is False or observed.get("available") is False
        ):
            observed_error = str(observed.get("errorCode", "") or "CAPABILITY_UNAVAILABLE")
            if normalized.startswith("desktop_os.") and observed_error in {
                "",
                "CAPABILITY_UNAVAILABLE",
                "native_snapshot_unavailable",
            } and _desktop_os_runtime_recovered(normalized):
                break
            if normalized.startswith("desktop_operator.") and observed_error in {"", "CAPABILITY_UNAVAILABLE", "native_snapshot_unavailable", "desktop_operator_unavailable"}:
                dependency = capability_dependency_status(normalized)
                if dependency.get("available") is True:
                    break
            if observed_error == "DEPENDENCY_UNAVAILABLE" and dependencies:
                missing_now = [
                    key
                    for key in dependencies
                    if not bool((snapshot.get(key) or {}).get("available", False))
                ]
                if not missing_now:
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
            approval_permission="side_effect",
            idempotency="non_idempotent",
        ).to_dict()

    migrated = capability_spec.spec_for(normalized)
    category = migrated.category if migrated is not None else "other"
    if migrated is not None:
        pass  # kategori spec'ten geldi; aşağıdaki legacy zincir atlanır
    elif normalized in {"file_read", "file_search", "directory_tree", "git_status", "git_diff", "file_write", "file_patch", "git_commit", "git_branch"}:
        category = "developer"
    elif normalized in {"web_research", "retrieve_context", "document_read", "ocr_read", "image_read", "image_fetch"}:
        category = "research_docs"
    elif normalized in {"document_write", "spreadsheet_write", "presentation_write", "canvas_write", "image_generate", "image_edit", "chart_generate"}:
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
    if normalized in {
        "browser_control",
        "play_media",
        "analyze_screen",
        "desktop_operator.observe_screen",
        "desktop_operator.locate",
        "desktop_operator.focus_window",
        "desktop_operator.execute_action",
        "desktop_operator.run",
        "shell_run",
        "desktop_os.processes",
        "desktop_os.active_window",
        "add_calendar_event",
        "delete_calendar_event",
        "add_reminder",
        "send_whatsapp_message",
        "save_whatsapp_contact",
        "email_send",
        "mcp_call_tool",
        "run_skill",
    } or normalized in _WRITE_CAPABILITIES:
        permissions = ("full_computer_access",)

    permission_class = "blocked"
    if normalized in _SIDE_EFFECT_CAPABILITIES:
        permission_class = "approval_required"
    elif permissions:
        permission_class = "degraded_but_safe"
    else:
        permission_class = "read_only"

    supported_platforms = (
        tuple(migrated.platforms)
        if migrated is not None
        else (("darwin",) if normalized in _DARWIN_ONLY_CAPABILITIES else ("darwin", "win32", "linux"))
    )
    verification_mode = migrated.verification_mode if migrated is not None else "tool_result"
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
    if migrated is not None:
        pass  # doğrulama modu spec'ten geldi
    elif normalized in _WRITE_CAPABILITIES or normalized in {"image_fetch", "file_write", "file_patch"}:
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
    if normalized in {"web_research", "document_write", "spreadsheet_write", "presentation_write", "canvas_write", "quantum_run_experiment", "image_generate", "image_edit", "image_fetch", "ocr_read", "file_search", "desktop_operator.observe_screen", "desktop_operator.locate", "desktop_operator.execute_action", "desktop_operator.run"}:
        timeout_seconds = 180 if normalized in {"image_generate", "image_edit"} else 120
    elif normalized == "shell_run":
        timeout_seconds = 180

    retryable = normalized not in _NON_RETRYABLE_SIDE_EFFECTS
    if normalized in _TRUSTED_IDEMPOTENT_WRITE_CAPABILITIES:
        approval_permission = "write"
        idempotency = "idempotent_write"
    elif normalized in _SIDE_EFFECT_CAPABILITIES:
        approval_permission = "side_effect"
        idempotency = "non_idempotent"
    elif normalized in _APPROVAL_READ_ONLY_CAPABILITIES:
        approval_permission = "read"
        idempotency = "read_only"
    else:
        # Registered-but-unclassified and unknown capabilities never gain
        # authority through a user mode. New capabilities must be explicitly
        # admitted to one of the approval allowlists above.
        approval_permission = "side_effect"
        idempotency = "non_idempotent"
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
        approval_permission=approval_permission,
        idempotency=idempotency,
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
            "image_edit",
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
    _migrated_status = capability_spec.spec_for(normalized)
    if _migrated_status is not None and _migrated_status.status_function:
        status_function_names.insert(0, _migrated_status.status_function)
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


def _writer_structured_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the useful part of an upstream result bounded and JSON-compatible."""
    structured: dict[str, Any] = {}
    for key in (
        "kind",
        "query",
        "languageHint",
        "summary",
        "sources",
        "columns",
        "previewRows",
        "rows",
        "profile",
        "items",
    ):
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "sources" and isinstance(value, list):
            cleaned_sources: list[dict[str, str]] = []
            for source in value[:8]:
                if not isinstance(source, dict):
                    continue
                title = _safe_writer_text(source.get("title", ""), 220)
                url = _safe_writer_text(source.get("url", ""), 1000)
                summary = _safe_writer_text(source.get("summary", "") or source.get("snippet", ""), 1200)
                if title or url or summary:
                    cleaned_sources.append({"title": title, "url": url, "summary": summary})
            if cleaned_sources:
                structured[key] = cleaned_sources
            continue
        if key in {"previewRows", "rows", "items"} and isinstance(value, list):
            structured[key] = value[:100]
            continue
        structured[key] = value[:12000] if isinstance(value, str) else value
    return structured


def _safe_writer_text(value: Any, limit: int = 12000) -> str:
    cleaned = "".join(
        char
        if char in {"\n", "\r", "\t"} or ord(char) >= 32
        else " "
        for char in str(value or "")
    )
    cleaned = " ".join(cleaned.replace("\ufffd", " ").split())
    return cleaned[:limit]


def _writer_source_context(args: dict[str, Any]) -> str:
    """Yazıcı araçlar (document/spreadsheet/presentation/canvas) için içerik
    bağlamı: açık sourceContext yoksa zincirdeki önceki adımın çıktısına düşer.
    Böylece "araştır ve belgele" gibi çok adımlı planlarda rapor, araştırma
    içeriğiyle dolu üretilir — boş şablon değil."""
    explicit = _safe_writer_text(args.get("sourceContext", "") or args.get("source_context", ""), 12000)
    dependency_results = args.get("_dependencyResults")
    if isinstance(dependency_results, dict) and dependency_results:
        parts: list[str] = []
        for step_id, payload in list(dependency_results.items())[:8]:
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("kind", "") or "").strip()
            if kind == "document_read":
                mode = str(payload.get("mode", "read") or "read").strip()
                if mode == "summary":
                    readable = _safe_writer_text(payload.get("summary", ""), 12000)
                elif mode == "bullets":
                    readable = "\n".join(
                        f"- {_safe_writer_text(item, 1200)}"
                        for item in payload.get("bullets", []) or []
                        if _safe_writer_text(item, 1200)
                    )
                else:
                    readable = _safe_writer_text(payload.get("text", "") or payload.get("summary", ""), 12000)
                if readable:
                    parts.append(readable[:12000])
                    continue

            readable_parts: list[str] = []
            for key in ("summary", "text", "body"):
                value = _safe_writer_text(payload.get(key, ""), 24000)
                if value:
                    readable_parts.append(value)
                    break
            bullets = payload.get("bullets")
            if isinstance(bullets, list) and not readable_parts:
                readable_parts.extend(
                    f"- {_safe_writer_text(item, 1200)}" for item in bullets if _safe_writer_text(item, 1200)
                )
            sources = payload.get("sources")
            if isinstance(sources, list):
                source_lines: list[str] = []
                for source in sources[:8]:
                    if not isinstance(source, dict):
                        continue
                    title = _safe_writer_text(source.get("title", ""), 220)
                    url = _safe_writer_text(source.get("url", ""), 1000)
                    summary = _safe_writer_text(source.get("summary", "") or source.get("snippet", ""), 700)
                    label = f"{title} - {url}" if title and url else title or url
                    if label:
                        source_lines.append(f"- {label}: {summary}".rstrip(": "))
                if source_lines:
                    readable_parts.append("Kaynaklar:\n" + "\n".join(source_lines))
            structured = _writer_structured_context(payload)
            if structured:
                readable_parts.insert(
                    0,
                    "Yapılandırılmış veri:\n"
                    + json.dumps(structured, ensure_ascii=False, default=str)
                )
            if readable_parts:
                parts.append(f"[{step_id}]\n" + "\n\n".join(readable_parts)[:24000])
        if parts:
            context = "\n\n".join(parts)[:48000]
            if explicit:
                context += "\n\n[Yazım talimatı]\n" + explicit[:12000]
            return context[:60000]
    previous = args.get("_previousResult")
    if isinstance(previous, dict):
        parts: list[str] = []
        for key in ("summary", "text", "body", "output"):
            value = _safe_writer_text(previous.get(key, ""), 24000)
            if value:
                parts.append(value)
                break
        bullets = previous.get("bullets")
        if isinstance(bullets, list):
            cleaned = [_safe_writer_text(item, 1200) for item in bullets if _safe_writer_text(item, 1200)]
            if cleaned:
                parts.append("\n".join(f"- {item}" for item in cleaned))
        sources = previous.get("sources")
        if isinstance(sources, list):
            lines = []
            for source in sources:
                if isinstance(source, dict):
                    label = _safe_writer_text(source.get("title", "") or source.get("url", ""), 1000)
                    snippet = _safe_writer_text(source.get("snippet", "") or source.get("summary", ""), 700)
                    if label or snippet:
                        lines.append(f"- {label}: {snippet}".rstrip(": "))
            if lines:
                parts.append("Kaynaklar:\n" + "\n".join(lines))
        structured = _writer_structured_context(previous)
        if structured:
            parts.insert(
                0,
                "Yapılandırılmış veri:\n"
                + json.dumps(structured, ensure_ascii=False, default=str)
            )
        if parts:
            context = "\n\n".join(parts)[:48000]
            if explicit:
                context += "\n\n[Yazım talimatı]\n" + explicit[:12000]
            return context[:60000]
    previous_output = _safe_writer_text(args.get("_previousOutput", ""), 48000)
    return explicit[:60000] or previous_output[:60000]


def _first_non_empty_text(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif value not in (None, "", [], {}):
            text = str(value).strip()
            if text:
                return text
    return ""


def _first_list(args: dict[str, Any], *keys: str) -> list[Any] | None:
    for key in keys:
        value = args.get(key)
        if isinstance(value, list):
            return value
    return None


def _first_dict(args: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = args.get(key)
        if isinstance(value, dict):
            return value
    return None


def _web_research_query(args: dict[str, Any]) -> str:
    query = _first_non_empty_text(
        args,
        "query",
        "q",
        "topic",
        "subject",
        "searchQuery",
        "search_query",
        "prompt",
        "question",
        "text",
    )
    if query:
        return query
    filters = _first_dict(args, "filters", "criteria")
    if filters:
        return " ".join(
            str(value).strip()
            for value in filters.values()
            if str(value or "").strip()
        )
    return ""


def _image_prompt(args: dict[str, Any]) -> str:
    prompt = _first_non_empty_text(
        args,
        "prompt",
        "imagePrompt",
        "image_prompt",
        "description",
        "visualDescription",
        "visual_description",
        "subject",
        "query",
        "text",
    )
    if prompt:
        return prompt
    spec = _first_dict(args, "image", "visual", "spec")
    if not spec:
        return ""
    pieces: list[str] = []
    for key in ("prompt", "description", "subject", "style", "mood", "background", "text"):
        value = str(spec.get(key, "") or "").strip()
        if value:
            pieces.append(value)
    return ", ".join(pieces)


def _document_prompt(args: dict[str, Any]) -> str:
    prompt = _first_non_empty_text(
        args,
        "prompt",
        "content",
        "body",
        "text",
        "markdown",
        "instructions",
        "instruction",
        "description",
    )
    if prompt:
        return prompt
    document = _first_dict(args, "document", "doc")
    if document:
        return _first_non_empty_text(document, "prompt", "content", "body", "text", "markdown", "summary")
    return ""


def _document_sections(args: dict[str, Any]) -> list[Any] | None:
    sections = _first_list(args, "sections", "chapters")
    if sections is not None:
        return sections
    document = _first_dict(args, "document", "doc")
    if document:
        return _first_list(document, "sections", "chapters")
    return None


def _document_blocks(args: dict[str, Any]) -> list[Any] | None:
    blocks = _first_list(args, "blocks", "contentBlocks", "content_blocks")
    if blocks is not None:
        return blocks
    document = _first_dict(args, "document", "doc")
    if document:
        return _first_list(document, "blocks", "contentBlocks", "content_blocks")
    return None


def _spreadsheet_payload(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": _first_non_empty_text(args, "prompt", "content", "summary", "description", "text"),
        "title": _first_non_empty_text(args, "title", "name", "sheetTitle", "sheet_title"),
        "columns": _first_list(args, "columns", "headers", "fields"),
        "rows": _first_list(args, "rows", "data", "items", "records", "values"),
    }
    table = _first_dict(args, "table", "worksheet", "sheet", "spreadsheet")
    sheets = _first_list(args, "sheets", "worksheets")
    if table is None and sheets and isinstance(sheets[0], dict):
        table = sheets[0]
    if table:
        payload["prompt"] = payload["prompt"] or _first_non_empty_text(table, "prompt", "content", "summary", "description", "text")
        payload["title"] = payload["title"] or _first_non_empty_text(table, "title", "name", "sheetTitle", "sheet_title")
        payload["columns"] = payload["columns"] or _first_list(table, "columns", "headers", "fields")
        payload["rows"] = payload["rows"] or _first_list(table, "rows", "data", "items", "records", "values")
    if payload["columns"] is None and isinstance(payload["rows"], list) and payload["rows"]:
        first = payload["rows"][0]
        if isinstance(first, list) and len(first) > 1 and all(not isinstance(item, (list, dict)) for item in first):
            payload["columns"] = first
            payload["rows"] = payload["rows"][1:]
    return payload


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
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
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
            _web_research_query(args),
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
            prompt=_image_prompt(args),
            outputPath=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            aspectRatio=str(args.get("aspectRatio", "") or args.get("aspect_ratio", "") or ""),
            imageSize=str(args.get("imageSize", "") or args.get("image_size", "") or ""),
            background=str(args.get("background", "auto") or "auto"),
            overwrite=bool(args.get("overwrite", False)),
            size=str(args.get("size", "") or ""),
            quality=str(args.get("quality", "") or ""),
        ),
        "image_edit": lambda args: _load_adapter("image_edit")(
            prompt=str(args.get("prompt", "") or ""),
            sourcePath=str(args.get("sourcePath", "") or args.get("source_path", "") or ""),
            sourcePaths=list(args.get("sourcePaths", []) or args.get("source_paths", []) or []),
            outputPath=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            aspectRatio=str(args.get("aspectRatio", "") or args.get("aspect_ratio", "") or ""),
            imageSize=str(args.get("imageSize", "") or args.get("image_size", "") or ""),
            overwrite=bool(args.get("overwrite", False)),
            _selectedPaths=list(args.get("_selectedPaths", []) or []),
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
            str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            list(args.get("_selectedPaths", []) or []),
        ),
        "math_solve": lambda args: _load_adapter("math_solve")(
            str(
                args.get("expression")
                or args.get("query")
                or args.get("problem")
                or args.get("input")
                or args.get("expr")
                or args.get("equation")
                or args.get("formula")
                or ""
            ),
            str(args.get("mode", "solve") or "solve"),
        ),
        "latex_parse": lambda args: _load_adapter("latex_parse")(
            str(args.get("expression", "") or ""),
            str(args.get("mode", "parse") or "parse"),
        ),
        "quantum_model_problem": lambda args: _load_adapter("quantum_model_problem")(
            prompt=str(args.get("prompt", "") or ""),
            problem_class=str(args.get("problemClass", "") or args.get("problem_class", "") or "optimization"),
            problem=dict(args.get("problem", {}) or {}) if isinstance(args.get("problem", {}), dict) else None,
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
            prompt=_document_prompt(args),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(args.get("title", "") or ""),
            sections=_document_sections(args),
            blocks=_document_blocks(args),
            source_path=str(args.get("sourcePath", "") or args.get("source_path", "") or ""),
            source_context=_writer_source_context(args),
            overwrite=bool(args.get("overwrite", False)),
            _selectedPaths=list(args.get("_selectedPaths", []) or []),
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
            _selectedPaths=list(args.get("_selectedPaths", []) or []),
        ),
        "spreadsheet_write": lambda args: _load_adapter("spreadsheet_write")(
            prompt=str(_spreadsheet_payload(args).get("prompt", "") or ""),
            output_path=str(args.get("outputPath", "") or args.get("output_path", "") or ""),
            title=str(_spreadsheet_payload(args).get("title", "") or ""),
            columns=_spreadsheet_payload(args).get("columns"),
            rows=_spreadsheet_payload(args).get("rows"),
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
            _selectedPaths=list(args.get("_selectedPaths", []) or []),
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
    # Tek Spec: göç edilen yetenekler için handler spec'ten üretilir
    # (eşleme + alias + tip dönüşümü tek yerde).
    for _spec_item in capability_spec.SPECS:
        handlers[_spec_item.name] = capability_spec.build_handler(_spec_item, _load_adapter)
    return handlers


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
        display = capability_display_name(tool_name)
        if error_code == "UNSUPPORTED_PLATFORM":
            message = f"{display} bu işletim sisteminde desteklenmiyor."
        elif error_code == "DEPENDENCY_UNAVAILABLE":
            message = f"{display} şu an kullanılamıyor: gerekli bileşen bu masaüstünde hazır değil."
        elif error_code == "OS_PERMISSION_REQUIRED":
            message = _system_permission_message(str(readiness.get("systemPermissionKey", "") or ""))
        else:
            message = f"{display} güvenli şekilde başlatılamadı."
        return {
            "ok": False,
            "tool": tool_name,
            "output": message,
            "error": {"code": error_code, "message": message},
            "readiness": readiness,
        }

    handler = _handlers().get(tool_name)
    if handler is None:
        display = capability_display_name(tool_name)
        message = f"{display} şu anda hazır değil."
        return {
            "ok": False,
            "tool": tool_name,
            "output": message,
            "error": {"code": "CAPABILITY_UNAVAILABLE", "message": message},
        }

    trust_context = state.get("runtime", {}).get("executionTrust", {}) if isinstance(state.get("runtime"), dict) else {}
    grant_guarded = isinstance(trust_context, dict) and bool(trust_context)
    grant_error = consume_grant_for_call(tool_name, payload, state)
    if grant_error is not None:
        return {
            "ok": False,
            "tool": tool_name,
            "output": "Görev yetkisi daha önce kullanılmış veya bu adıma uymuyor.",
            "error": {"code": grant_error.code, "message": "Görev yetkisi daha önce kullanılmış veya bu adıma uymuyor."},
        }

    output: Any = None
    handler_completed = False
    try:
        output = handler(payload)
        handler_completed = True
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
    finally:
        if grant_guarded:
            try:
                finish_grant_for_call(payload, ok=handler_completed, result=output)
            except Exception:
                pass

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


_CONFIRMED_READBACK_STATUSES = {
    "closed_confirmed",
    "foreground_confirmed",
    "frontmost_verified",
    "state_verified",
    "read_back_verified",
    "created",
    "updated",
    "launched",
    "saved",
}
_READBACK_BOOL_FIELDS = (
    ("closedConfirmed", "closed_confirmed"),
    ("foregroundConfirmed", "foreground_confirmed"),
    ("frontmostVerified", "frontmost_verified"),
    ("stateVerified", "state_verified"),
    ("readBackVerified", "read_back_verified"),
    ("created", "created"),
    ("updated", "updated"),
    ("mcpToolExecuted", "mcp_tool_executed"),
)


def extract_state_readback(result: dict[str, Any]) -> dict[str, Any] | None:
    """Yeteneğin ürettiği gerçek-durum gözlemini makine-okur kanıta çevirir.

    "Komut hata vermedi" (ok) DEĞİL, "etki gerçekten gözlendi" anlamına gelen
    alanlar aranır: uygulama kapandı/açıldı mı, dosya diskte var mı, kaç dosya
    kaydedildi. Gözlemlenecek bir son-durum yoksa None döner (bu adımın yan
    etkisi yok ya da doğrulanamıyor demektir). "prove it" ilkesinin çekirdeği.
    """
    payload = result.get("result")
    if not isinstance(payload, dict):
        return None
    for key, status in _READBACK_BOOL_FIELDS:
        if payload.get(key) is True:
            return {"observed": True, "status": status, "field": key}
    try:
        saved = int(payload.get("savedCount", 0) or 0)
    except (TypeError, ValueError):
        saved = 0
    if saved > 0:
        return {"observed": True, "status": "saved", "field": "savedCount", "count": saved}
    out_path = str(payload.get("outputPath", "") or payload.get("path", "") or "").strip()
    if out_path:
        try:
            exists = Path(out_path).expanduser().is_file()
        except (OSError, RuntimeError, ValueError):
            exists = False
        return {
            "observed": exists,
            "status": "file_exists" if exists else "file_missing",
            "field": "outputPath",
        }
    verification_status = str(payload.get("verificationStatus", "") or "").strip().lower()
    if verification_status:
        return {
            "observed": verification_status in _CONFIRMED_READBACK_STATUSES,
            "status": verification_status,
            "field": "verificationStatus",
        }
    if payload.get("processObserved") is True:
        return {"observed": True, "status": "process_observed", "field": "processObserved"}
    return None


def safe_tool_event(tool_name: str, result: dict[str, Any], *, source: str) -> dict[str, Any]:
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    output = str(result.get("output") or error.get("message") or "").strip()
    ok = bool(result.get("ok"))
    readback = extract_state_readback(result) if ok else None
    event: dict[str, Any] = {
        "tool": tool_name,
        "source": source,
        "ok": ok,
        "output": output[:1000],
        "errorCode": str(error.get("code", "") or ""),
        # verified = araç başarılı VE (gözlenecek son-durum yoksa | gözlendiyse).
        # Yan etki iddia edilip gözlenemezse (ör. kapatıldı ama süreç hâlâ var)
        # bu False olur; görev "tamamlandı" iddiasını buna dayandırır.
        "verified": ok and (readback is None or readback.get("observed") is True),
    }
    if readback is not None:
        event["stateReadback"] = readback
    return event


def run_capability_text(tool_name: str, args: dict[str, Any] | None, state: dict[str, Any]) -> str:
    result = run_capability(tool_name, args, state)
    if result.get("ok"):
        return str(result.get("output", "") or "İşlem tamamlandı.")
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    return str(error.get("message") or result.get("output") or "Araç güvenli şekilde tamamlanamadı.")
