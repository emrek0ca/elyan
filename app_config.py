# emre koca tarafından yapılmıştır — @emrekoca
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LEGACY_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Elyan"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Elyan"
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "Elyan"
    return Path.home() / ".config" / "Elyan"


CONFIG_DIR = _user_data_dir() / "config"
CONFIG_PATH = CONFIG_DIR / "api_keys.json"


DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "gemini_model": "models/gemini-2.5-flash",
    "voice": "Charon",
    "youtube_api_key": "",
    "youtube_channel_handle": "",
    "backend_base_url": "https://api.elyan.dev",
}

LEGACY_BACKEND_BASE_URL = "http://84.247.172.213:4000"
PUBLIC_BACKEND_BASE_URL = "https://api.elyan.dev"


def load_app_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        elif LEGACY_CONFIG_PATH.exists():
            raw = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                json.dumps(raw, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            raw = {}
        if isinstance(raw, dict):
            config.update(raw)
        backend_base_url = str(config.get("backend_base_url", "") or "").strip().rstrip("/")
        if backend_base_url == LEGACY_BACKEND_BASE_URL:
            config["backend_base_url"] = PUBLIC_BACKEND_BASE_URL
    except Exception:
        pass
    return config


def save_app_config(updates: dict) -> dict:
    config = load_app_config()
    for key, value in (updates or {}).items():
        if value is None:
            continue
        config[key] = value
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    return config


def get_app_config_value(key: str, default=None):
    return load_app_config().get(key, default)


def has_gemini_api_key() -> bool:
    value = str(get_app_config_value("gemini_api_key", "") or "").strip()
    return bool(value)
