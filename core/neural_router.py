from typing import Dict, Any
from config.elyan_config import elyan_config
from core.model_catalog import default_model_for_provider, normalize_model_name
from utils.logger import get_logger

logger = get_logger("neural_router")

class NeuralRoleMapper:
    """Routes tasks to specific LLM models based on complexity and role."""

    ROLE_NAMES = (
        "reasoning",
        "inference",
        "creative",
        "code",
        "router",
        "critic",
        "worker",
        "research_worker",
        "code_worker",
        "planning",
        "qa",
    )
    ROLE_ALIASES = {
        "router": "inference",
        "critic": "reasoning",
        "worker": "reasoning",
        "research_worker": "reasoning",
        "code_worker": "code",
        "planning": "reasoning",
        "qa": "reasoning",
    }

    def __init__(self):
        self.role_map: Dict[str, Dict[str, Any]] = {}
        self._load_from_config()

    def _load_from_config(self):
        default_cfg = self._default_model_config()
        config_roles = elyan_config.get("models.roles", {}) or {}
        if not isinstance(config_roles, dict):
            config_roles = {}

        refreshed: Dict[str, Dict[str, Any]] = {}
        for role in self.ROLE_NAMES:
            role_cfg = config_roles.get(role)
            if isinstance(role_cfg, dict):
                refreshed[role] = {
                    "provider": role_cfg.get("provider") or default_cfg["provider"],
                    "model": role_cfg.get("model") or default_cfg["model"],
                }
            else:
                refreshed[role] = dict(default_cfg)
        self.role_map = refreshed

    def _default_model_config(self) -> Dict[str, Any]:
        provider = elyan_config.get("models.default.provider", "ollama")
        provider = str(provider or "").strip() or "ollama"
        model = elyan_config.get("models.default.model")
        if not model:
            model = default_model_for_provider(provider)
        return {"provider": provider, "model": normalize_model_name(provider, model)}

    def get_model_for_role(self, role: str) -> Dict[str, Any]:
        """
        Return provider/model for a role.
        If router is disabled, always return models.default.
        """
        # Keep mapper in sync with runtime config changes.
        self._load_from_config()
        default_cfg = self._default_model_config()
        router_enabled = bool(elyan_config.get("router.enabled", True))
        if not router_enabled:
            return default_cfg

        role_name = (role or "inference").lower()
        if role_name == "router":
            config_roles = elyan_config.get("models.roles", {}) or {}
            router_cfg = config_roles.get("router") if isinstance(config_roles, dict) else None
            local_default = {
                "provider": "ollama",
                "model": normalize_model_name(
                    "ollama",
                    str(
                        elyan_config.get("models.providers.ollama.model", "")
                        or elyan_config.get("models.providers.ollama.default_model", "")
                        or elyan_config.get("models.local.model", default_model_for_provider("ollama"))
                    ),
                ),
            }
            if isinstance(router_cfg, dict) and (router_cfg.get("provider") or router_cfg.get("model")):
                return {
                    "provider": router_cfg.get("provider") or local_default["provider"],
                    "model": normalize_model_name(router_cfg.get("provider") or local_default["provider"], router_cfg.get("model") or local_default["model"]),
                }
            return local_default
        selected = self.role_map.get(role_name)
        if not isinstance(selected, dict):
            alias = self.ROLE_ALIASES.get(role_name, role_name)
            selected = self.role_map.get(alias) or default_cfg
        if not isinstance(selected, dict):
            return default_cfg
        return {
            "provider": selected.get("provider") or default_cfg["provider"],
            "model": normalize_model_name(selected.get("provider") or default_cfg["provider"], selected.get("model") or default_cfg["model"]),
        }

    def detect_role(self, prompt: str) -> str:
        p = prompt.lower()
        
        # 1. Code Detection
        if any(kw in p for kw in ["kod", "yazılım", "python", "javascript", "react", "debug", "html"]):
            return "code"
            
        # 2. Reasoning Detection (Complex planning)
        if any(kw in p for kw in ["planla", "tasarla", "analiz et", "neden", "mimari", "strateji"]):
            return "reasoning"
            
        # 3. Creative Detection
        if any(kw in p for kw in ["hikaye", "şiir", "blog", "yaratıcı", "fikir", "slogan"]):
            return "creative"
            
        # Default to fast inference
        return "inference"

    def route(self, prompt: str) -> Dict[str, Any]:
        role = self.detect_role(prompt)
        model_cfg = self.get_model_for_role(role)
        
        # Complexity scoring (simple heuristic for now)
        complexity = 0.8 if role in ["code", "reasoning"] else 0.3
        
        # Reasoning Budget: Decide if this task needs the full factory flow
        needs_factory = complexity > 0.7 or len(prompt.split()) > 25
        
        # Fallback configuration
        fallback_cfg = self._default_model_config()
        
        return {
            "role": role,
            "model": model_cfg["model"],
            "provider": model_cfg["provider"],
            "fallback_model": fallback_cfg["model"],
            "fallback_provider": fallback_cfg["provider"],
            "complexity": complexity,
            "reasoning_budget": "high" if needs_factory else "low"
        }

# Global instance
neural_router = NeuralRoleMapper()
