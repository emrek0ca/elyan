"""
Elyan Job Templates — Zorunlu İş Şablonları

Her job tipi için izinli tool seti, QA kontrolleri ve delivery modu.
Serbest stil job'lar bu template'lere uydurulur.
"""

from typing import Dict, List, Any, Optional
from utils.logger import get_logger

logger = get_logger("job_templates")


# ── Template Tanımları ────────────────────────────────────────

JOB_TEMPLATES: Dict[str, Dict[str, Any]] = {

    "web_project": {
        "description": "Web sitesi / web uygulaması oluşturma",
        "allowed_tools": [
            "create_web_project_scaffold", "write_file", "read_file",
            "create_directory", "browser", "take_screenshot",
        ],
        "qa_checks": ["file_exists", "html_valid", "min_file_size"],
        "delivery_mode": "file_path",
        "expected_extensions": [".html", ".css", ".js", ".jsx", ".tsx"],
        "min_files": 1,
        "keywords": ["site", "web", "html", "sayfa", "portfolio", "landing", "dashboard",
                      "uygulama", "app", "react", "next", "frontend"],
    },

    "research_report": {
        "description": "Araştırma raporu / analiz / derin araştırma",
        "allowed_tools": [
            "web_search", "deep_research", "advanced_research", "write_file", "write_word",
            "read_file", "write_excel",
        ],
        "qa_checks": ["file_exists", "file_not_empty", "min_file_size"],
        "delivery_mode": "file_path",
        "expected_extensions": [".md", ".docx", ".txt", ".pdf"],
        "min_files": 1,
        "keywords": ["araştır", "analiz", "rapor", "research", "report", "incele",
                      "özetle", "hakkında", "nedir"],
    },

    "file_operations": {
        "description": "Dosya/klasör işlemleri (oluşturma, kopyalama, taşıma, silme)",
        "allowed_tools": [
            "write_file", "read_file", "delete_file", "copy_file", "move_file",
            "create_directory", "create_folder", "list_directory", "list_files", "find_files", "search_files",
        ],
        "qa_checks": ["file_exists"],
        "delivery_mode": "file_path",
        "expected_extensions": [],
        "min_files": 0,
        "keywords": ["dosya", "klasör", "oluştur", "sil", "taşı", "kopyala", "kaydet",
                      "yaz", "file", "folder", "create", "delete", "move"],
    },

    "code_project": {
        "description": "Yazılım projesi / script / kod yazma",
        "allowed_tools": [
            "write_file", "read_file", "execute_python", "execute_code",
            "terminal_command", "create_directory",
        ],
        "qa_checks": ["file_exists", "file_not_empty"],
        "delivery_mode": "file_path",
        "expected_extensions": [".py", ".js", ".ts", ".go", ".rs", ".java"],
        "min_files": 1,
        "keywords": ["kod", "script", "python", "program", "geliştir", "code",
                      "implement", "function", "class", "api", "fonksiyon",
                      "algoritma", "algorithm", "fibonacci", "sorting", "compile"],
    },

    "data_analysis": {
        "description": "Veri analizi / Excel / tablo oluşturma",
        "allowed_tools": [
            "write_excel", "write_file", "read_file", "execute_python",
            "web_search",
        ],
        "qa_checks": ["file_exists", "file_not_empty"],
        "delivery_mode": "file_path",
        "expected_extensions": [".xlsx", ".csv", ".json"],
        "min_files": 1,
        "keywords": ["excel", "tablo", "veri", "analiz", "data", "csv", "grafik",
                      "chart", "istatistik"],
    },

    "communication": {
        "description": "Sohbet / selamlaşma / bilgi isteme",
        "allowed_tools": [],
        "qa_checks": [],
        "delivery_mode": "inline",
        "expected_extensions": [],
        "min_files": 0,
        "keywords": ["merhaba", "selam", "naber", "nasıl", "teşekkür", "sağol",
                      "hello", "hi", "thanks", "tamam", "ok"],
    },

    "system_ops": {
        "description": "Sistem operasyonları / kurulum / konfigürasyon",
        "allowed_tools": [
            "terminal_command", "system_info", "list_directory", "read_file",
            "write_file", "find_files", "run_safe_command", "execute_shell_command",
        ],
        "qa_checks": [],
        "delivery_mode": "inline",
        "expected_extensions": [],
        "min_files": 0,
        "keywords": ["kur", "install", "güncelle", "update", "sistem", "system",
                      "process", "kontrol", "check", "durum", "status"],
    },

    "browser_task": {
        "description": "Tarayıcı görevi / web scraping / ekran görüntüsü",
        "allowed_tools": [
            "browser", "take_screenshot", "web_search", "browser_navigate",
            "browser_click", "browser_type", "write_file",
        ],
        "qa_checks": ["file_exists"],
        "delivery_mode": "file_path",
        "expected_extensions": [".png", ".jpg", ".pdf"],
        "min_files": 0,
        "keywords": ["aç", "git", "browse", "screenshot", "ekran", "tara", "scrape",
                      "sayfayı", "siteye"],
    },

    "api_integration": {
        "description": "API entegrasyonu / endpoint test / webhook akışı",
        "allowed_tools": [
            "http_request", "graphql_query", "api_health_check",
            "write_file", "read_file", "run_safe_command",
        ],
        "qa_checks": ["file_exists", "file_not_empty"],
        "delivery_mode": "file_path",
        "expected_extensions": [".json", ".md", ".txt", ".http"],
        "min_files": 0,
        "keywords": [
            "api", "endpoint", "rest", "graphql", "webhook", "http",
            "postman", "curl", "integration", "entegrasyon", "request", "response",
        ],
    },
}


def detect_job_type(user_input: str) -> str:
    """Kullanıcı girdisinden job tipini tespit et."""
    low = user_input.lower()

    # High-confidence direct routing for API-centric tasks.
    api_markers = ("api", "graphql", "endpoint", "webhook", "http ", "rest ")
    if sum(1 for marker in api_markers if marker in low) >= 2:
        return "api_integration"
    
    best_type = "communication"
    best_score = 0

    for jtype, template in JOB_TEMPLATES.items():
        score = sum(1 for kw in template["keywords"] if kw in low)
        if score > best_score:
            best_score = score
            best_type = jtype

    return best_type


def get_template(job_type: str) -> Dict[str, Any]:
    """Job tipi için template döndür."""
    return JOB_TEMPLATES.get(job_type, JOB_TEMPLATES["communication"])


def get_allowed_tools(job_type: str) -> List[str]:
    """Job tipi için izinli tool listesi."""
    return get_template(job_type).get("allowed_tools", [])


def build_contract_from_template(job_type: str, user_input: str) -> dict:
    """Template'den JobContract parametreleri oluştur."""
    template = get_template(job_type)
    return {
        "job_type": job_type,
        "allowed_tools": template["allowed_tools"],
        "qa_checks": template["qa_checks"],
        "delivery_mode": template["delivery_mode"],
        "expected_extensions": template["expected_extensions"],
        "min_files": template.get("min_files", 0),
    }
