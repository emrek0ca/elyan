import os
import platform
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _keychain_get(key_name: str) -> str:
    """
    BUG-SEC-005: Load secret from macOS Keychain.
    Falls back to empty string if not on macOS or key not found.
    """
    if platform.system() != "Darwin":
        return ""
    try:
        from security.keychain import KeychainManager
        val = KeychainManager.get_key(key_name)
        return val or ""
    except Exception:
        return ""


def _get_secret(env_var: str, keychain_key: str = None) -> str:
    """
    Get secret: Keychain first (macOS), then .env.
    Keychain takes priority for security.
    """
    if keychain_key:
        kc_val = _keychain_get(keychain_key)
        if kc_val:
            return kc_val
    return os.getenv(env_var, "")

PROJECT_ROOT = Path(__file__).parent.parent
HOME_DIR = Path.home()
ELYAN_DIR = HOME_DIR / ".elyan"
LOGS_DIR = ELYAN_DIR / "logs"
MEMORY_DIR = ELYAN_DIR / "memory"

# Essential Directories for Validator
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

FULL_DISK_ACCESS = os.getenv("FULL_DISK_ACCESS", "true").lower() in ("1", "true", "yes", "on")

# Ensure essential dirs exist early
for d in [ELYAN_DIR, LOGS_DIR, MEMORY_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Sensitive values — Keychain first, .env fallback (BUG-SEC-005)
TELEGRAM_TOKEN = _get_secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token")
OPENAI_API_KEY = _get_secret("OPENAI_API_KEY", "openai_api_key")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY", "anthropic_api_key")
GOOGLE_API_KEY = _get_secret("GOOGLE_API_KEY", "google_api_key")

# System Identity
APP_NAME = "Elyan"
VERSION = "18.0.0"

# Task Execution
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "120"))
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
