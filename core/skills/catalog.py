"""Built-in and curated skills/workflow catalog for Elyan."""
from __future__ import annotations

from typing import Dict, Any, List


def get_builtin_skill_catalog() -> Dict[str, Dict[str, Any]]:
    """
    Returns builtin/curated skill metadata keyed by skill name.
    """
    return {
        "system": {
            "name": "system",
            "version": "1.2.0",
            "description": "Sistem kontrolü, ekran görüntüsü, uygulama ve süreç bilgileri",
            "category": "core",
            "required_tools": ["get_system_info", "take_screenshot", "open_app", "close_app", "get_process_info"],
            "dependencies": [],
            "commands": ["sysinfo", "screenshot", "open_app", "close_app", "process"],
            "source": "builtin",
        },
        "files": {
            "name": "files",
            "version": "1.2.0",
            "description": "Dosya okuma/yazma/listeleme/arama operasyonları",
            "category": "productivity",
            "required_tools": ["list_files", "read_file", "write_file", "search_files", "create_folder"],
            "dependencies": [],
            "commands": ["list", "read", "write", "search", "mkdir"],
            "source": "builtin",
        },
        "research": {
            "name": "research",
            "version": "1.3.0",
            "description": "Web araştırma, derin araştırma ve özetleme",
            "category": "analysis",
            "required_tools": ["web_search", "fetch_page", "advanced_research"],
            "dependencies": [],
            "commands": ["search", "deep_research", "summarize"],
            "source": "builtin",
        },
        "browser": {
            "name": "browser",
            "version": "1.1.0",
            "description": "Tarayıcı otomasyonu ve web navigasyon",
            "category": "automation",
            "required_tools": ["open_url", "take_screenshot", "extract_text"],
            "dependencies": [],
            "commands": ["navigate", "screenshot", "extract"],
            "source": "builtin",
        },
        "office": {
            "name": "office",
            "version": "1.1.0",
            "description": "Word/Excel/PDF işleme ve belge üretimi",
            "category": "document",
            "required_tools": ["write_word", "write_excel", "read_pdf", "generate_document_pack"],
            "dependencies": [],
            "commands": ["word", "excel", "pdf", "report_pack"],
            "source": "builtin",
        },
        "email": {
            "name": "email",
            "version": "1.0.0",
            "description": "E-posta gönderme ve inbox işlemleri",
            "category": "communication",
            "required_tools": ["send_email"],
            "dependencies": [],
            "commands": ["send", "inbox"],
            "source": "builtin",
        },
        "voice": {
            "name": "voice",
            "version": "1.0.0",
            "description": "Konuşma-metin ve metin-konuşma işlemleri",
            "category": "multimodal",
            "required_tools": ["transcribe_audio_file", "speak_text_local"],
            "dependencies": [],
            "commands": ["transcribe", "speak"],
            "source": "curated",
        },
        "calendar": {
            "name": "calendar",
            "version": "1.0.0",
            "description": "Takvim ve hatırlatıcı yönetimi",
            "category": "productivity",
            "required_tools": ["get_today_events", "create_event", "create_reminder"],
            "dependencies": [],
            "commands": ["today", "create_event", "reminder"],
            "source": "curated",
        },
        "multimodal": {
            "name": "multimodal",
            "version": "1.0.0",
            "description": "Görsel paket üretimi ve görsel analiz",
            "category": "multimodal",
            "required_tools": ["create_visual_asset_pack", "analyze_and_narrate_image"],
            "dependencies": [],
            "commands": ["visual_pack", "analyze_image"],
            "source": "curated",
        },
    }


def get_builtin_workflow_catalog() -> Dict[str, Dict[str, Any]]:
    """
    Skill+tool linked workflow templates.
    - executable=True: deterministik olarak doğrudan çalıştırılabilir
    - executable=False: entegrasyon şablonu (plan/recipe)
    """
    return {
        "wallpaper_with_proof": {
            "id": "wallpaper_with_proof",
            "name": "Wallpaper + Proof",
            "version": "1.0.0",
            "description": "Görselden duvar kağıdı ayarla ve kanıt ekran görüntüsü üret.",
            "category": "desktop",
            "required_skills": ["system", "files"],
            "required_tools": ["set_wallpaper", "take_screenshot"],
            "steps": ["set_wallpaper", "take_screenshot"],
            "trigger_markers": ["duvar kağıdı", "wallpaper", "arka plan"],
            "executable": True,
            "auto_intent": True,
            "source": "builtin",
        },
        "api_health_get_save": {
            "id": "api_health_get_save",
            "name": "API Health + GET + Save",
            "version": "1.0.0",
            "description": "Endpoint health check + GET isteği + result.json/summary.txt kaydı.",
            "category": "integration",
            "required_skills": ["research", "files"],
            "required_tools": ["api_health_check", "http_request", "write_file"],
            "steps": ["api_health_check", "http_request", "write_file", "write_file"],
            "trigger_markers": ["health check", "get", "result.json", "summary.txt"],
            "executable": True,
            "auto_intent": True,
            "source": "builtin",
        },
        "office_sales_report_pipeline": {
            "id": "office_sales_report_pipeline",
            "name": "Sales Report Pipeline",
            "version": "1.0.0",
            "description": "ERP/CRM satış verisi -> analiz -> rapor/PDF -> mail akışı için şablon.",
            "category": "office",
            "required_skills": ["office", "email", "research"],
            "required_tools": ["read_excel", "analyze_excel_data", "write_word", "generate_document_pack", "send_email"],
            "steps": ["read_excel", "analyze_excel_data", "write_word", "generate_document_pack", "send_email"],
            "trigger_markers": ["satış raporu", "pdf", "yönetime mail"],
            "executable": False,
            "auto_intent": False,
            "source": "builtin",
        },
        "contract_expiry_scan": {
            "id": "contract_expiry_scan",
            "name": "Contract Expiry Scan",
            "version": "1.0.0",
            "description": "Sözleşme klasörlerini tarayıp bitiş tarihi yaklaşanları raporlar.",
            "category": "compliance",
            "required_skills": ["files", "office"],
            "required_tools": ["search_files", "read_file", "write_file"],
            "steps": ["search_files", "read_file", "write_file"],
            "trigger_markers": ["sözleşme", "süresi dolacak", "contract expiry"],
            "executable": False,
            "auto_intent": False,
            "source": "builtin",
        },
        "incident_log_analysis": {
            "id": "incident_log_analysis",
            "name": "Incident Log Analysis",
            "version": "1.0.0",
            "description": "Log dosyalarını analiz edip hata özeti ve aksiyon listesi üretir.",
            "category": "ops",
            "required_skills": ["system", "files", "research"],
            "required_tools": ["search_files", "read_file", "write_file", "run_safe_command"],
            "steps": ["search_files", "read_file", "run_safe_command", "write_file"],
            "trigger_markers": ["log analiz", "incident", "hata raporu"],
            "executable": False,
            "auto_intent": False,
            "source": "builtin",
        },
        "priority_planning_assistant": {
            "id": "priority_planning_assistant",
            "name": "Priority Planning",
            "version": "1.0.0",
            "description": "Görevleri önceliklendirip zaman planı şablonu çıkarır.",
            "category": "planning",
            "required_skills": ["research", "calendar"],
            "required_tools": ["create_reminder", "create_event", "write_file"],
            "steps": ["create_event", "create_reminder", "write_file"],
            "trigger_markers": ["önceliklendir", "acil 3 iş", "takvime yerleştir"],
            "executable": False,
            "auto_intent": False,
            "source": "builtin",
        },
    }


def list_catalog() -> List[Dict[str, Any]]:
    return list(get_builtin_skill_catalog().values())


def list_workflow_catalog() -> List[Dict[str, Any]]:
    return list(get_builtin_workflow_catalog().values())
