"""
Built-in and curated skills catalog for Elyan.
"""
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


def list_catalog() -> List[Dict[str, Any]]:
    return list(get_builtin_skill_catalog().values())
