import json
import os
import logging
import platform
from pathlib import Path
from typing import Any
from config.elyan_config import elyan_config
from core.model_catalog import default_model_for_provider
from security.keychain import keychain

logger = logging.getLogger("config.settings_manager")

_SETTINGS_PROVIDER_ALIASES = {
    "api": "gemini",
    "google": "gemini",
    "local": "ollama",
}
_RUNTIME_PROVIDER_ALIASES = {
    "api": "google",
    "gemini": "google",
    "local": "ollama",
}
_SETTINGS_PROVIDER_ORDER = ["groq", "gemini", "openai", "anthropic", "ollama"]
_API_ENV_KEYS = {
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _normalize_settings_provider(provider: Any) -> str:
    raw = str(provider or "").strip().lower()
    return _SETTINGS_PROVIDER_ALIASES.get(raw, raw)


def _normalize_runtime_provider(provider: Any) -> str:
    raw = str(provider or "").strip().lower()
    return _RUNTIME_PROVIDER_ALIASES.get(raw, raw)

# Default settings
DEFAULT_SETTINGS = {
    "bot_name": "Elyan Bot",
    "auto_start": False,
    "ui_theme": "Sistem",
    "ui_language": "Türkçe",
    "minimize_to_tray": True,
    "notifications_enabled": True,
    "llm_provider": "groq",
    "llm_model": "llama-3.3-70b-versatile",
    "llm_temperature": 0.7,
    "llm_max_tokens": 2048,
    "llm_fallback_mode": "aggressive",
    "llm_fallback_order": _SETTINGS_PROVIDER_ORDER.copy(),
    "llm_sticky_selection": True,
    "assistant_style": "professional_friendly_short",
    "full_disk_access": True,
    "onboarding_completed": False,
    "show_first_run_tips": True,
    "communication_tone": "professional_friendly",
    "response_length": "short",
    "preferred_language": "auto",
    "enabled_languages": ["tr", "en"],
    "task_planning_depth": "adaptive",
    "planner_max_steps": 10,
    "auto_replan_enabled": True,
    "auto_replan_max_attempts": 1,
    "require_plan_confirmation": True,
    "publish_ready_threshold": 78.0,
    "cost_guard": True,
    "pricing_rates_per_1k": {},
    "monthly_budget_usd": 20.0,
    "budget_alert_threshold_pct": 80,
    "pricing_alerts_enabled": True,
    "privacy_mode_strict": True,
    "privacy_redact_storage": True,
    "privacy_redact_logs": True,
    "assistant_expertise": "advanced",
    "ollama_host": "http://localhost:11434",
    "api_key": "",
    "telegram_token": "",
    "allowed_user_ids": [],
    "photo_save_dir": "~/Desktop/TelegramInbox/Photos",
    "document_save_dir": "~/Desktop/TelegramInbox/Files",
    "context_memory": 10,
    # v23.0 New Keys
    "autonomy_level": "Balanced",
    "operator_mode_level": "Confirmed",
    "allowed_tools": ["all"],
    "vision_frequency": 30,
    "vision_quality": "balanced",
    "media_polling": True,
    "glass_opacity": 0.8,
    "log_level": "INFO"
}

class SettingsPanel:
    """Manage bot settings and configuration (Manager Level - No UI Dependencies)"""

    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path) if config_path else self._default_config_path()
        self.env_path = Path(__file__).parent.parent / ".env"
        self._settings = {}
        self._migrate_old_settings()
        self._load()

    def _default_config_path(self) -> Path:
        """Get unified config file path (v23.0)"""
        preferred = Path.home() / ".elyan"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            probe = preferred / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return preferred / "settings.json"
        except Exception:
            fallback = Path(__file__).parent.parent / ".elyan"
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(f"Home config dir not writable, using fallback: {fallback}")
            return fallback / "settings.json"

    def _migrate_old_settings(self):
        """Migrate from old ~/.config/elyan-bot path if exists"""
        old_path = Path.home() / ".config" / "elyan-bot" / "settings.json"
        new_path = self._default_config_path()
        
        if old_path.exists() and not new_path.exists():
            try:
                import shutil
                shutil.copy2(old_path, new_path)
                logger.info(f"Migrated settings from {old_path} to {new_path}")
            except Exception as e:
                logger.error(f"Migration error: {e}")

    def _load(self):
        """Load settings from file"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self._settings = json.loads(content)
                    else:
                        self._settings = {}
                # Migrations & Sanitization (v23.0)
                # 1. Migrate old key to new key
                if "telegram_bot_token" in self._settings and ("telegram_token" not in self._settings or self._settings.get("telegram_token") == "test_token"):
                    old_val = self._settings.get("telegram_bot_token")
                    if old_val and old_val != "test_token":
                        self._settings["telegram_token"] = old_val
                        logger.info("Migrated telegram_bot_token to telegram_token")

                # 2. Sanitization: Don't allow 'test_token' to persist if we have a better one in .env or old key
                if self._settings.get("telegram_token") == "test_token":
                    import os
                    env_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if env_token and env_token != "test_token":
                        self._settings["telegram_token"] = env_token
                        logger.info("Restored telegram_token from .env")

                # Ensure all default keys exist
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in self._settings:
                        self._settings[key] = value

                # Sanitize new fields
                fallback_mode = str(self._settings.get("llm_fallback_mode", "aggressive")).lower()
                if fallback_mode not in {"aggressive", "conservative"}:
                    self._settings["llm_fallback_mode"] = "aggressive"

                fallback_order = self._settings.get("llm_fallback_order", DEFAULT_SETTINGS["llm_fallback_order"])
                if not isinstance(fallback_order, list) or not fallback_order:
                    fallback_order = DEFAULT_SETTINGS["llm_fallback_order"].copy()

                normalized = []
                for provider in fallback_order:
                    p = _normalize_settings_provider(provider)
                    if p in _SETTINGS_PROVIDER_ORDER and p not in normalized:
                        normalized.append(p)
                for provider in _SETTINGS_PROVIDER_ORDER:
                    if provider not in normalized:
                        normalized.append(provider)
                self._settings["llm_fallback_order"] = normalized
                if not isinstance(self._settings.get("llm_sticky_selection"), bool):
                    self._settings["llm_sticky_selection"] = True

                style = str(self._settings.get("assistant_style", "professional_friendly_short")).strip()
                if not style:
                    self._settings["assistant_style"] = "professional_friendly_short"

                if self._settings.get("communication_tone") not in {"professional_friendly", "mentor", "formal"}:
                    self._settings["communication_tone"] = "professional_friendly"
                if self._settings.get("response_length") not in {"short", "medium", "detailed"}:
                    self._settings["response_length"] = "short"
                preferred_language = str(self._settings.get("preferred_language", "auto")).lower()
                if preferred_language not in {"auto", "tr", "en", "es", "de", "fr", "it", "pt", "ar", "ru"}:
                    self._settings["preferred_language"] = "auto"
                enabled_languages = self._settings.get("enabled_languages", ["tr", "en"])
                if not isinstance(enabled_languages, list) or not enabled_languages:
                    enabled_languages = ["tr", "en"]
                normalized_langs = []
                for lang in enabled_languages:
                    l = str(lang).lower().strip()
                    if l in {"tr", "en", "es", "de", "fr", "it", "pt", "ar", "ru"} and l not in normalized_langs:
                        normalized_langs.append(l)
                self._settings["enabled_languages"] = normalized_langs or ["tr", "en"]
                if self._settings.get("task_planning_depth") not in {"adaptive", "compact", "deep"}:
                    self._settings["task_planning_depth"] = "adaptive"
                if not isinstance(self._settings.get("planner_max_steps"), int) or self._settings.get("planner_max_steps") is None:
                    self._settings["planner_max_steps"] = 10
                if not isinstance(self._settings.get("auto_replan_enabled"), bool):
                    self._settings["auto_replan_enabled"] = True
                try:
                    attempts = int(self._settings.get("auto_replan_max_attempts", 1))
                    self._settings["auto_replan_max_attempts"] = max(0, min(3, attempts))
                except Exception:
                    self._settings["auto_replan_max_attempts"] = 1
                if not isinstance(self._settings.get("require_plan_confirmation"), bool):
                    self._settings["require_plan_confirmation"] = True
                try:
                    threshold = float(self._settings.get("publish_ready_threshold", 78.0))
                    self._settings["publish_ready_threshold"] = max(50.0, min(95.0, threshold))
                except Exception:
                    self._settings["publish_ready_threshold"] = 78.0
                if not isinstance(self._settings.get("cost_guard"), bool):
                    self._settings["cost_guard"] = True
                if not isinstance(self._settings.get("pricing_rates_per_1k"), dict):
                    self._settings["pricing_rates_per_1k"] = {}
                try:
                    self._settings["monthly_budget_usd"] = float(self._settings.get("monthly_budget_usd", 20.0))
                except Exception:
                    self._settings["monthly_budget_usd"] = 20.0
                try:
                    threshold = int(self._settings.get("budget_alert_threshold_pct", 80))
                    self._settings["budget_alert_threshold_pct"] = max(10, min(100, threshold))
                except Exception:
                    self._settings["budget_alert_threshold_pct"] = 80
                if not isinstance(self._settings.get("pricing_alerts_enabled"), bool):
                    self._settings["pricing_alerts_enabled"] = True
                if not isinstance(self._settings.get("privacy_mode_strict"), bool):
                    self._settings["privacy_mode_strict"] = True
                if not isinstance(self._settings.get("privacy_redact_storage"), bool):
                    self._settings["privacy_redact_storage"] = True
                if not isinstance(self._settings.get("privacy_redact_logs"), bool):
                    self._settings["privacy_redact_logs"] = True
                if self._settings.get("assistant_expertise") not in {"basic", "advanced", "expert"}:
                    self._settings["assistant_expertise"] = "advanced"
                if self._settings.get("operator_mode_level") not in {"Advisory", "Assisted", "Confirmed", "Trusted", "Operator"}:
                    self._settings["operator_mode_level"] = "Confirmed"
                if not isinstance(self._settings.get("full_disk_access"), bool):
                    self._settings["full_disk_access"] = True
                if not str(self._settings.get("photo_save_dir", "")).strip():
                    self._settings["photo_save_dir"] = DEFAULT_SETTINGS["photo_save_dir"]
                if not str(self._settings.get("document_save_dir", "")).strip():
                    self._settings["document_save_dir"] = DEFAULT_SETTINGS["document_save_dir"]
                self._overlay_runtime_llm_settings()
                
                logger.info(f"Settings loaded from {self.config_path}")
            else:
                self._settings = DEFAULT_SETTINGS.copy()
                # Check .env for initial values if file doesn't exist
                import os
                env_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if env_token and env_token != "test_token":
                    self._settings["telegram_token"] = env_token

                self._overlay_runtime_llm_settings()
                self._save()
                logger.info("Created default settings")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            self._settings = DEFAULT_SETTINGS.copy()

    def _save(self):
        """Save settings to file and sync with .env"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)

            self._sync_to_runtime_config()
            # Sync to .env for core logic (LLMClient, etc)
            self._sync_to_env()
            logger.info("Settings saved and synced to .env")
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    def _provider_config_from_runtime(self, provider: str) -> dict[str, Any]:
        runtime_provider = _normalize_runtime_provider(provider)
        cfg = elyan_config.get(f"models.providers.{runtime_provider}", {}) or {}
        if runtime_provider == "google" and not cfg:
            cfg = elyan_config.get("models.providers.gemini", {}) or {}
        return dict(cfg)

    def _overlay_runtime_llm_settings(self):
        """Mirror active runtime model selection from elyan.json into legacy settings."""
        try:
            default_cfg = elyan_config.get("models.default", {}) or {}
            fallback_cfg = elyan_config.get("models.fallback", {}) or {}
            local_cfg = elyan_config.get("models.local", {}) or {}

            provider = _normalize_settings_provider(
                default_cfg.get("provider") or self._settings.get("llm_provider", "groq")
            )
            if provider in _SETTINGS_PROVIDER_ORDER:
                self._settings["llm_provider"] = provider

            model = str(default_cfg.get("model") or "").strip()
            if model:
                self._settings["llm_model"] = model

            host = str(local_cfg.get("baseUrl") or local_cfg.get("endpoint") or "").strip()
            if host:
                self._settings["ollama_host"] = host

            provider_cfg = self._provider_config_from_runtime(provider)
            api_key = str(provider_cfg.get("apiKey") or "").strip()
            if provider != "ollama" and api_key and not api_key.startswith("$"):
                self._settings["api_key"] = api_key

            fallback_order: list[str] = []
            for item in [provider, fallback_cfg.get("provider")]:
                normalized = _normalize_settings_provider(item)
                if normalized in _SETTINGS_PROVIDER_ORDER and normalized not in fallback_order:
                    fallback_order.append(normalized)
            for item in DEFAULT_SETTINGS["llm_fallback_order"]:
                if item not in fallback_order:
                    fallback_order.append(item)
            self._settings["llm_fallback_order"] = fallback_order
        except Exception as exc:
            logger.debug(f"Runtime config overlay skipped: {exc}")

    def _sync_to_runtime_config(self):
        """Keep elyan.json aligned with the desktop settings panel."""
        try:
            provider = _normalize_settings_provider(self._settings.get("llm_provider", "groq"))
            runtime_provider = _normalize_runtime_provider(provider)
            model = str(self._settings.get("llm_model", "") or "").strip() or default_model_for_provider(runtime_provider)
            host = str(
                self._settings.get("ollama_host", "http://localhost:11434")
                or "http://localhost:11434"
            ).strip()
            api_key = str(self._settings.get("api_key", "") or "").strip()

            elyan_config.set("models.default", {"provider": runtime_provider, "model": model})

            fallback_order = self._settings.get("llm_fallback_order", DEFAULT_SETTINGS["llm_fallback_order"])
            normalized_order: list[str] = []
            if isinstance(fallback_order, list):
                for item in fallback_order:
                    normalized = _normalize_settings_provider(item)
                    if normalized in _SETTINGS_PROVIDER_ORDER and normalized not in normalized_order:
                        normalized_order.append(normalized)
            if provider not in normalized_order:
                normalized_order.insert(0, provider)

            fallback_provider = next((item for item in normalized_order if item != provider), "ollama")
            runtime_fallback = _normalize_runtime_provider(fallback_provider)
            existing_fallback = elyan_config.get("models.fallback", {}) or {}
            fallback_provider_cfg = self._provider_config_from_runtime(fallback_provider)
            fallback_model = (
                model
                if runtime_fallback == runtime_provider
                else str(
                    existing_fallback.get("model")
                    or fallback_provider_cfg.get("model")
                    or default_model_for_provider(runtime_fallback)
                ).strip()
            )
            elyan_config.set("models.fallback", {"provider": runtime_fallback, "model": fallback_model})

            elyan_config.set("models.local.provider", "ollama")
            elyan_config.set("models.local.baseUrl", host)
            if provider == "ollama":
                elyan_config.set("models.local.model", model)
            else:
                elyan_config.set(f"models.providers.{runtime_provider}.model", model)
                env_key = _API_ENV_KEYS.get(runtime_provider)
                if env_key and api_key:
                    elyan_config.set(f"models.providers.{runtime_provider}.apiKey", f"${env_key}")

            current_registry = elyan_config.get("models.registry", []) or []
            if not isinstance(current_registry, list):
                current_registry = []
            registry_id = f"desktop-primary:{runtime_provider}:{model}"
            next_registry = []
            matched = False
            for item in current_registry:
                if not isinstance(item, dict):
                    continue
                item_provider = _normalize_runtime_provider(item.get("provider") or item.get("type"))
                item_model = str(item.get("model") or "").strip()
                item_id = str(item.get("id") or "").strip()
                if item_id.startswith("desktop-primary:") and item_id != registry_id:
                    continue
                if item_provider == runtime_provider and item_model == model:
                    merged = dict(item)
                    merged["enabled"] = True
                    try:
                        merged["priority"] = min(int(merged.get("priority", 12)), 12)
                    except Exception:
                        merged["priority"] = 12
                    next_registry.append(merged)
                    matched = True
                    continue
                next_registry.append(item)
            if not matched:
                next_registry.append(
                    {
                        "id": registry_id,
                        "provider": runtime_provider,
                        "model": model,
                        "alias": "Desktop Primary",
                        "enabled": True,
                        "roles": ["inference", "reasoning", "planning", "code", "qa"],
                        "priority": 12,
                    }
                )
            elyan_config.set("models.registry", next_registry)
        except Exception as exc:
            logger.error(f"Error syncing settings to elyan.json: {exc}")

    def _sync_to_env(self):
        """Update .env file with current settings"""
        if not self.env_path.exists():
            return

        try:
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Normalize provider name: "gemini" → "api" for .env compatibility
            _provider = _normalize_settings_provider(self._settings.get("llm_provider", "groq"))
            _llm_type = "api" if _provider == "gemini" else _provider

            env_updates = {
                "LLM_TYPE": _llm_type,
                "OLLAMA_HOST": self._settings.get("ollama_host", "http://localhost:11434"),
                "MODEL_NAME": self._settings.get("llm_model", "llama-3.3-70b-versatile"),
                "ALLOWED_USER_IDS": ",".join(self._settings.get("allowed_user_ids", []) if isinstance(self._settings.get("allowed_user_ids"), list) else [str(self._settings.get("allowed_user_ids"))]),
                "FULL_DISK_ACCESS": "true" if bool(self._settings.get("full_disk_access", True)) else "false",
            }
            
            # Match API key to specific provider
            provider = env_updates["LLM_TYPE"]
            api_key = self._settings.get("api_key", "")
            keychain_mode = platform.system() == "Darwin" and keychain.is_available()

            # BUG-SEC-005: Keep secrets in Keychain on macOS, avoid plaintext .env.
            if keychain_mode:
                telegram_token = str(self._settings.get("telegram_token", "") or "")
                if telegram_token:
                    keychain.set_key("telegram_bot_token", telegram_token)

                if api_key:
                    if provider == "api" or provider == "gemini":  # Handle both aliases
                        keychain.set_key("google_api_key", api_key)
                    elif provider == "groq":
                        keychain.set_key("groq_api_key", api_key)
                    elif provider == "openai":
                        keychain.set_key("openai_api_key", api_key)
                    elif provider == "anthropic":
                        keychain.set_key("anthropic_api_key", api_key)

                # Keep sensitive values empty in .env when keychain is active.
                env_updates["TELEGRAM_BOT_TOKEN"] = ""
                env_updates["GOOGLE_API_KEY"] = ""
                env_updates["GROQ_API_KEY"] = ""
                env_updates["OPENAI_API_KEY"] = ""
                env_updates["ANTHROPIC_API_KEY"] = ""
            else:
                env_updates["TELEGRAM_BOT_TOKEN"] = self._settings.get("telegram_token", "")
                if provider == "api" or provider == "gemini":  # Handle both aliases
                    env_updates["GOOGLE_API_KEY"] = api_key
                elif provider == "groq":
                    env_updates["GROQ_API_KEY"] = api_key
                elif provider == "openai":
                    env_updates["OPENAI_API_KEY"] = api_key
                elif provider == "anthropic":
                    env_updates["ANTHROPIC_API_KEY"] = api_key

            new_lines = []
            seen_keys = set()
            
            for line in lines:
                key_match = line.split("=")
                if len(key_match) > 1:
                    key = key_match[0].strip()
                    if key in env_updates:
                        new_lines.append(f"{key}={env_updates[key]}\n")
                        seen_keys.add(key)
                        continue
                new_lines.append(line)

            # Add missing keys
            for key, val in env_updates.items():
                if key not in seen_keys:
                    new_lines.append(f"{key}={val}\n")

            with open(self.env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        except Exception as e:
            logger.error(f"Error syncing to .env: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        self._settings[key] = value
        self._save()
        return True

    def update(self, updates: dict) -> bool:
        for key, value in updates.items():
            self._settings[key] = value
        self._save()
        return True

# Aliases for compatibility
SettingsManager = SettingsPanel
