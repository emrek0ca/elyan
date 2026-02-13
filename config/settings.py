import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
LLM_TYPE = os.getenv("LLM_TYPE", "groq")  # groq | api | openai | ollama
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

ALLOWED_USER_IDS_STR = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(x.strip()) for x in ALLOWED_USER_IDS_STR.split(",") if x.strip()]

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Model: env'den oku, yoksa provider'a gore default
MODEL_NAME = os.getenv("MODEL_NAME", "")

def get_model_name() -> str:
    """Get the configured model name based on provider"""
    if MODEL_NAME:
        return MODEL_NAME

    # Provider-based defaults
    if LLM_TYPE == "groq":
        return "llama-3.3-70b-versatile"
    elif LLM_TYPE == "api":
        return "gemini-2.0-flash"
    elif LLM_TYPE == "openai":
        return "gpt-4o-mini"
    elif LLM_TYPE == "ollama":
        return _pick_best_ollama_model()
    return "llama-3.3-70b-versatile"

def _pick_best_ollama_model() -> str:
    """Pick best installed Ollama model (only called when Ollama is selected)"""
    import subprocess
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
        full_names = []
        for line in out.stdout.strip().splitlines()[1:]:
            if line.split():
                full_names.append(line.split()[0])
    except Exception:
        return "llama3.2:3b"

    for candidate in ["llama3.1", "llama3", "qwen2.5", "mistral", "phi3"]:
        for name in full_names:
            if name.startswith(candidate):
                return name
    return full_names[0] if full_names else "llama3.2:3b"

# Backward compat
OLLAMA_MODEL = get_model_name() if LLM_TYPE == "ollama" else "llama3.2:3b"

OLLAMA_OPTIONS = {
    "num_predict": 1500,
    "temperature": 0.1,
    "top_p": 0.9,
    "repeat_penalty": 1.1
}

TASK_TIMEOUT = 60
CIRCUIT_BREAKER_THRESHOLD = 5
HOME_DIR = Path.home()
DESKTOP = HOME_DIR / "Desktop"
DOCUMENTS = HOME_DIR / "Documents"
DOWNLOADS = HOME_DIR / "Downloads"

ALLOWED_DIRECTORIES = [
    HOME_DIR,
    DESKTOP,
    DOCUMENTS,
    DOWNLOADS,
    HOME_DIR / "Pictures",
    HOME_DIR / "Music",
    HOME_DIR / "Movies",
]

# File access scope
# True: allow broad filesystem access except explicitly blocked sensitive paths.
# False: restrict to ALLOWED_DIRECTORIES and home.
FULL_DISK_ACCESS = os.getenv("FULL_DISK_ACCESS", "true").lower() in ("1", "true", "yes", "on")

# LLM Cache Settings
CACHE_ENABLED = True
CACHE_MAX_SIZE = 500
CACHE_TTL = 1800

# Office Document Settings
MAX_FILE_SIZE_MB = 10
MAX_DOCUMENT_CHARS = 10000

# Web Research Settings
WEB_REQUEST_TIMEOUT = 30
WEB_RATE_LIMIT_SECONDS = 5
MAX_RESEARCH_TASKS = 3

# Verification Strategy Settings
SKIP_VERIFICATION_TOOLS = {
    "take_screenshot", "get_brightness", "set_brightness",
    "get_system_info", "list_files", "read_file", "write_file",
    "get_running_apps", "wifi_status", "wifi_toggle",
    "bluetooth_status", "get_appearance", "get_today_events",
    "get_reminders", "search_files", "spotlight_search",
    "get_process_info", "open_app", "open_url", "close_app",
    "set_volume", "toggle_dark_mode", "move_file", "copy_file",
    "rename_file", "create_folder", "read_clipboard",
    "write_clipboard", "send_notification", "create_note",
    "list_notes", "search_notes", "web_search",
    "advanced_research", "smart_summarize", "create_smart_file",
    "analyze_document",
}

ALWAYS_VERIFY_TOOLS = {
    "delete_file",
    "run_safe_command",
}

# Security Settings
QR_TOKEN_VALIDITY_SECONDS = 300
BLOCKED_WEB_DOMAINS = [
    "localhost", "127.0.0.1", "0.0.0.0",
    "192.168.", "10.", "172.16.",
]

MACOS_ALLOWED_OPERATIONS = [
    "toggle_dark_mode", "wifi_status", "wifi_toggle",
    "get_today_events", "create_event", "get_reminders",
    "create_reminder", "spotlight_search", "get_system_preferences",
]

SYSTEM_PROMPT = ''' Elyan - macOS uzerinde calisan profesyonel bir Turkce dijital asistan.

GOREVLERIN:
- Kullanicinin istegini analiz et ve en uygun tool'u sec
- Turkce, samimi ama profesyonel bir dilde yanit ver
- Emoji kullanma, gereksiz uzatma yapma
- Bilmiyorsan durustce soyle

YANIT FORMATI (sadece JSON):
{{"action":"tool_adi", "message":"kisa aciklama", ...parametreler}}
Sohbet icin: {{"action":"chat", "message":"yanitin"}}

KURALLAR:
1. Istegi anla, dogru tool'u sec, parametreleri dogru ayarla
2. Dosya yolu belirtilmediyse Desktop varsay
3. Belirsizliklerde kullaniciya sor (chat ile)
4. Coklu islem gerekiyorsa adim adim planla
5. Hata durumunda net ve anlasilir aciklama yap'''
