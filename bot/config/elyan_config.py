import json
try:
    import json5 as _json5_mod
    _HAS_JSON5 = True
except ImportError:
    _HAS_JSON5 = False
import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import ValidationError
from core.domain.models import AppConfig, AgentConfig
from config import settings
from security.keychain import KeychainManager
from utils.logger import get_logger

logger = get_logger("config")


def _default_config() -> AppConfig:
    """Roadmap-compatible default configuration."""
    return AppConfig(
        agent=AgentConfig(),
        models={
            "default": {"provider": "anthropic", "model": "claude-opus-4-5-20251101"},
            "fallback": {"provider": "openai", "model": "gpt-4o"},
            "local": {"provider": "ollama", "model": "llama3", "baseUrl": "http://localhost:11434"},
        },
        tools={
            "allow": [
                "group:fs",
                "group:web",
                "group:ui",
                "group:runtime",
                "group:messaging",
                "group:automation",
                "group:memory",
                "browser",
            ],
            "deny": ["exec"],
            "requireApproval": ["delete_file", "write_file"],
        },
        sandbox={"enabled": True, "mode": "docker"},
        memory={
            "enabled": True,
            "path": "~/.elyan/memory/",
            "maxSizeMB": 500,
            "maxUserStorageGB": 10,
            "localOnly": True,
        },
        security={
            "operatorMode": "Confirmed",
            "requirePlanApproval": True,
            "auditLog": True,
            "rateLimitPerMinute": 20,
        },
        gateway={"port": 18789, "host": "127.0.0.1", "corsOrigins": ["http://localhost:3000"]},
    )

class ConfigurationManager:
    def __init__(self):
        self._config_path = settings.ELYAN_DIR / "elyan.json"
        self._data: Optional[AppConfig] = None
        self.load()

    def load(self):
        """Load and validate configuration."""
        if not self._config_path.exists():
            self._data = _default_config()
            self.save()
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                content = f.read()
            # BUG-FUNC-010: Support JSON5 (comments, trailing commas)
            if _HAS_JSON5:
                raw_data = _json5_mod.loads(content)
            else:
                raw_data = json.loads(content)
            # Pydantic validation
            self._data = AppConfig(**raw_data)
        except (ValidationError, json.JSONDecodeError, Exception) as e:
            logger.warning(f"Config corrupted or incompatible, resetting: {e}")
            self._data = _default_config()
            self.save()

    def save(self):
        """Persist configuration."""
        if not self._data: return
        
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                f.write(self._data.model_dump_json(indent=2))
        except Exception as e:
            logger.error(f"Config Save Error: {e}")

    @property
    def config(self) -> AppConfig:
        return self._data

    def _resolve_secret_ref(self, value: Any) -> Any:
        """
        Resolve '$ENV_VAR' references using env first, then Keychain.
        Keeps the original reference if no value is found.
        """
        if not isinstance(value, str) or not value.startswith("$") or len(value) < 2:
            return value

        env_key = value[1:]
        env_val = os.getenv(env_key, "")
        if env_val:
            return env_val

        keychain_key = KeychainManager.key_for_env(env_key)
        if keychain_key:
            kc_val = KeychainManager.get_key(keychain_key)
            if kc_val:
                return kc_val
        return value

    def _resolve_refs_recursive(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._resolve_refs_recursive(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_refs_recursive(v) for v in value]
        return self._resolve_secret_ref(value)

    # Helper for legacy code compatibility
    def get(self, key: str, default=None):
        """Retrieve value by dot notation string."""
        try:
            parts = key.split('.')
            val = self._data.model_dump()
            for p in parts:
                val = val[p]
            return self._resolve_refs_recursive(val)
        except:
            return default

    def set(self, key: str, value: Any):
        """Set value by dot notation (updates model)."""
        # This is complex with Pydantic models directly. 
        # For simplicity in this CLI phase, we update the dict representation and re-validate.
        current = self._data.model_dump()
        keys = key.split('.')
        ref = current
        for k in keys[:-1]:
            if k not in ref: ref[k] = {}
            ref = ref[k]
        ref[keys[-1]] = value
        
        # Re-validate
        try:
            self._data = AppConfig(**current)
            self.save()
        except ValidationError as e:
            logger.error(f"Invalid setting value: {e}")

# Singleton
elyan_config = ConfigurationManager()
