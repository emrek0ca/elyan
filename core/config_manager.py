"""
Dynamic Configuration Management
Hot reload, environment-based config, feature flags, A/B testing
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import os

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("config_manager")


class ConfigSource(Enum):
    """Configuration source types"""
    FILE = "file"
    ENVIRONMENT = "environment"
    DATABASE = "database"
    REMOTE = "remote"


@dataclass
class FeatureFlag:
    """Feature flag definition"""
    name: str
    enabled: bool
    rollout_percentage: float = 100.0  # 0-100
    user_whitelist: List[str] = None
    user_blacklist: List[str] = None
    conditions: Dict[str, Any] = None

    def __post_init__(self):
        if self.user_whitelist is None:
            self.user_whitelist = []
        if self.user_blacklist is None:
            self.user_blacklist = []
        if self.conditions is None:
            self.conditions = {}


class ConfigManager:
    """
    Dynamic Configuration Management
    - Hot reload configuration
    - Environment-based config
    - Feature flags
    - A/B testing
    - Config validation
    - Config versioning
    - Change notifications
    """

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.feature_flags: Dict[str, FeatureFlag] = {}
        self.config_file = HOME_DIR / ".elyan" / "dynamic_config.json"
        self.flags_file = HOME_DIR / ".elyan" / "feature_flags.json"
        self.env_prefix = "elyan_"

        # Change listeners
        self.listeners: List[Callable[[str, Any, Any], None]] = []

        # Config versioning
        self.version = 0
        self.history: List[Dict[str, Any]] = []

        # Load configuration
        self._load_config()
        self._load_feature_flags()

        # Environment override
        self._load_from_env()

        logger.info("Configuration Manager initialized")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, persist: bool = True):
        """Set configuration value"""
        old_value = self.get(key)

        # Update config
        keys = key.split('.')
        config = self.config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

        # Increment version
        self.version += 1

        # Save to history
        self.history.append({
            "version": self.version,
            "key": key,
            "old_value": old_value,
            "new_value": value,
            "timestamp": time.time()
        })

        # Notify listeners
        self._notify_listeners(key, old_value, value)

        # Persist if requested
        if persist:
            self._save_config()

        logger.info(f"Config updated: {key} = {value}")

    def reload(self):
        """Reload configuration from file"""
        self._load_config()
        self._load_feature_flags()
        self._load_from_env()
        logger.info("Configuration reloaded")

    def _load_config(self):
        """Load configuration from file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                logger.info(f"Loaded configuration from {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    def _save_config(self):
        """Save configuration to file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.debug("Configuration saved")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _load_from_env(self):
        """Load configuration from environment variables"""
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                config_key = key[len(self.env_prefix):].lower().replace('_', '.')

                # Try to parse as JSON
                try:
                    parsed_value = json.loads(value)
                except:
                    parsed_value = value

                self.set(config_key, parsed_value, persist=False)

        logger.debug("Environment variables loaded")

    def register_listener(self, listener: Callable[[str, Any, Any], None]):
        """Register a configuration change listener"""
        self.listeners.append(listener)

    def _notify_listeners(self, key: str, old_value: Any, new_value: Any):
        """Notify all listeners of config change"""
        for listener in self.listeners:
            try:
                listener(key, old_value, new_value)
            except Exception as e:
                logger.error(f"Listener error: {e}")

    # Feature Flags

    def create_feature_flag(
        self,
        name: str,
        enabled: bool = False,
        rollout_percentage: float = 100.0,
        user_whitelist: Optional[List[str]] = None,
        conditions: Optional[Dict[str, Any]] = None
    ):
        """Create a feature flag"""
        flag = FeatureFlag(
            name=name,
            enabled=enabled,
            rollout_percentage=rollout_percentage,
            user_whitelist=user_whitelist or [],
            conditions=conditions or {}
        )

        self.feature_flags[name] = flag
        self._save_feature_flags()

        logger.info(f"Feature flag created: {name}")

    def is_feature_enabled(
        self,
        feature_name: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Check if feature is enabled for user"""
        if feature_name not in self.feature_flags:
            return False

        flag = self.feature_flags[feature_name]

        # Global disable
        if not flag.enabled:
            return False

        # Check blacklist
        if user_id and user_id in flag.user_blacklist:
            return False

        # Check whitelist
        if user_id and flag.user_whitelist and user_id in flag.user_whitelist:
            return True

        # Check rollout percentage
        if flag.rollout_percentage < 100.0:
            # Simple hash-based deterministic rollout
            if user_id:
                import hashlib
                hash_value = int(hashlib.sha256(f"{feature_name}:{user_id}".encode()).hexdigest(), 16)
                percentage = (hash_value % 100)
                if percentage >= flag.rollout_percentage:
                    return False

        # Check conditions
        if flag.conditions and context:
            for key, expected_value in flag.conditions.items():
                if key not in context or context[key] != expected_value:
                    return False

        return True

    def update_feature_flag(
        self,
        feature_name: str,
        enabled: Optional[bool] = None,
        rollout_percentage: Optional[float] = None
    ):
        """Update feature flag"""
        if feature_name not in self.feature_flags:
            logger.warning(f"Feature flag not found: {feature_name}")
            return

        flag = self.feature_flags[feature_name]

        if enabled is not None:
            flag.enabled = enabled

        if rollout_percentage is not None:
            flag.rollout_percentage = rollout_percentage

        self._save_feature_flags()
        logger.info(f"Feature flag updated: {feature_name}")

    def get_feature_flags(self) -> Dict[str, Dict[str, Any]]:
        """Get all feature flags"""
        return {
            name: {
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
                "user_whitelist": flag.user_whitelist,
                "conditions": flag.conditions
            }
            for name, flag in self.feature_flags.items()
        }

    def _load_feature_flags(self):
        """Load feature flags from file"""
        try:
            if self.flags_file.exists():
                with open(self.flags_file, 'r') as f:
                    data = json.load(f)

                for name, flag_data in data.items():
                    self.feature_flags[name] = FeatureFlag(
                        name=name,
                        enabled=flag_data.get("enabled", False),
                        rollout_percentage=flag_data.get("rollout_percentage", 100.0),
                        user_whitelist=flag_data.get("user_whitelist", []),
                        user_blacklist=flag_data.get("user_blacklist", []),
                        conditions=flag_data.get("conditions", {})
                    )

                logger.info(f"Loaded {len(self.feature_flags)} feature flags")
        except Exception as e:
            logger.error(f"Failed to load feature flags: {e}")

    def _save_feature_flags(self):
        """Save feature flags to file"""
        try:
            self.flags_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                name: {
                    "enabled": flag.enabled,
                    "rollout_percentage": flag.rollout_percentage,
                    "user_whitelist": flag.user_whitelist,
                    "user_blacklist": flag.user_blacklist,
                    "conditions": flag.conditions
                }
                for name, flag in self.feature_flags.items()
            }

            with open(self.flags_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug("Feature flags saved")
        except Exception as e:
            logger.error(f"Failed to save feature flags: {e}")

    # A/B Testing

    def get_ab_variant(
        self,
        experiment_name: str,
        user_id: str,
        variants: List[str] = None
    ) -> str:
        """Get A/B test variant for user"""
        if variants is None:
            variants = ["A", "B"]

        # Deterministic assignment based on user_id
        import hashlib
        hash_value = int(hashlib.sha256(f"{experiment_name}:{user_id}".encode()).hexdigest(), 16)
        variant_index = hash_value % len(variants)

        return variants[variant_index]

    # Config Validation

    def validate_config(self, schema: Dict[str, Any]) -> bool:
        """Validate configuration against schema"""
        # Simple validation (could be extended with jsonschema)
        for key, expected_type in schema.items():
            value = self.get(key)

            if value is None:
                logger.warning(f"Missing config key: {key}")
                return False

            if not isinstance(value, expected_type):
                logger.warning(f"Invalid type for {key}: expected {expected_type}, got {type(value)}")
                return False

        return True

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get configuration change history"""
        return self.history[-limit:]

    def rollback_to_version(self, version: int) -> bool:
        """Rollback configuration to a specific version"""
        # Find all changes after the target version
        changes_to_revert = [
            h for h in reversed(self.history)
            if h["version"] > version
        ]

        for change in changes_to_revert:
            self.set(change["key"], change["old_value"], persist=False)

        self._save_config()
        self.version = version

        logger.info(f"Rolled back to version {version}")
        return True

    def get_summary(self) -> Dict[str, Any]:
        """Get configuration summary"""
        return {
            "version": self.version,
            "config_keys": len(self._flatten_dict(self.config)),
            "feature_flags": len(self.feature_flags),
            "enabled_flags": sum(1 for f in self.feature_flags.values() if f.enabled),
            "listeners": len(self.listeners),
            "history_entries": len(self.history)
        }

    def _flatten_dict(self, d: Dict, parent_key: str = '') -> Dict[str, Any]:
        """Flatten nested dictionary"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)


# Global instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get or create global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
