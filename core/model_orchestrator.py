import logging
from typing import Dict, Any, List, Optional
from config.elyan_config import elyan_config
from core.neural_router import neural_router
from security.keychain import keychain, KeychainManager
from utils.logger import get_logger
import os

logger = get_logger("model_orchestrator")

class ModelOrchestrator:
    def __init__(self):
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.active_provider = elyan_config.get("models.default.provider", "ollama") or "ollama"
        self.metrics: Dict[str, Dict[str, Any]] = {}
        self._load_providers()

    def record_metric(self, provider: str, success: bool, latency: float):
        if provider not in self.metrics:
            self.metrics[provider] = {"success": 0, "failure": 0, "latencies": []}
        
        m = self.metrics[provider]
        if success:
            m["success"] += 1
        else:
            m["failure"] += 1
        
        m["latencies"].append(latency)
        if len(m["latencies"]) > 50: m["latencies"].pop(0)

    def get_health_report(self) -> Dict[str, Any]:
        report = {}
        for p, m in self.metrics.items():
            total = m["success"] + m["failure"]
            rate = (m["success"] / total * 100) if total > 0 else 0
            avg_latency = sum(m["latencies"]) / len(m["latencies"]) if m["latencies"] else 0
            report[p] = {
                "success_rate": f"{rate:.1f}%",
                "avg_latency": f"{avg_latency:.3f}s",
                "total_calls": total,
                "status": self.providers.get(p, {}).get("status", "unknown")
            }
        return report

    def _load_from_keychain(self, provider: str) -> Optional[str]:
        # Try env var first (fastest)
        env_key = f"{provider.upper()}_API_KEY"
        val = os.getenv(env_key)
        if val: return val
        
        # Then try keychain
        return keychain.get_key(KeychainManager.key_for_env(env_key) or env_key.lower())

    def _load_providers(self):
        """elyan.json ve Keychain'den tüm sağlayıcıları yükle"""
        available_types = ["openai", "anthropic", "google", "ollama", "groq"]
        default_cfg = elyan_config.get("models.default", {}) or {}
        fallback_cfg = elyan_config.get("models.fallback", {}) or {}
        
        for p_type in available_types:
            config = elyan_config.get(f"models.providers.{p_type}", {})
            
            # Check for API key (except for local/ollama)
            api_key = None
            if p_type != "ollama":
                # Check config first, then env/keychain
                api_key = config.get("apiKey") or self._load_from_keychain(p_type)
            
            if p_type == "ollama" or api_key:
                candidate_model = (
                    config.get("default_model")
                    or config.get("model")
                    or (
                        default_cfg.get("model")
                        if default_cfg.get("provider") == p_type
                        else None
                    )
                    or (
                        fallback_cfg.get("model")
                        if fallback_cfg.get("provider") == p_type
                        else None
                    )
                    or self._get_default_model(p_type)
                )
                self.providers[p_type] = {
                    "type": p_type,
                    "model": self._normalize_model_for_provider(p_type, candidate_model),
                    "apiKey": api_key,
                    "endpoint": config.get("endpoint"),
                    "status": "configured"
                }
        
        logger.info(f"Loaded providers: {list(self.providers.keys())}")

    def _get_default_model(self, p_type: str) -> str:
        defaults = {
            "ollama": "llama3.1:8b",
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-latest",
            "google": "gemini-2.0-flash",
            "groq": "llama-3.3-70b-versatile"
        }
        return defaults.get(p_type, "unknown")

    def _normalize_model_for_provider(self, provider: str, model: Optional[str]) -> str:
        model = (model or "").strip()
        if not model:
            return self._get_default_model(provider)

        low = model.lower()
        if provider == "openai":
            if low.startswith(("gpt-", "o1", "o3", "gpt4")):
                return model
            return self._get_default_model(provider)
        if provider == "anthropic":
            if "claude" in low:
                return model
            return self._get_default_model(provider)
        if provider == "google":
            if "gemini" in low:
                return model
            return self._get_default_model(provider)
        if provider == "groq":
            if low.startswith(("llama", "mixtral", "qwen", "deepseek")):
                return model
            return self._get_default_model(provider)
        # ollama/local: user may have arbitrary local model names.
        return model

    def get_best_available(self, role: str = "inference", exclude: set = None) -> Dict[str, Any]:
        """İstenen rol için en iyi aktif sağlayıcıyı döner (hariç tutulanlar dışında)"""
        if exclude is None: exclude = set()
        
        # 1. Ask Neural Router for the preferred provider/model for this role
        try:
            if hasattr(neural_router, "get_model_for_role"):
                preferred = neural_router.get_model_for_role(role) or {}
            else:
                preferred = {}
        except Exception:
            preferred = {}
            
        pref_provider = preferred.get("provider") or preferred.get("type")
        if pref_provider and pref_provider not in self.providers:
            pref_provider = None
        pref_model = preferred.get("model")
        
        if pref_provider in self.providers and pref_provider not in exclude:
            config = self.providers[pref_provider].copy()
            if pref_model:
                config["model"] = self._normalize_model_for_provider(pref_provider, pref_model)
            return config

        # 2. Fallback: Search in priority list, avoiding excluded ones
        priority = ["groq", "openai", "anthropic", "google", "ollama"]
        # Include active provider at top of priority if not already there
        if self.active_provider not in priority:
            priority.insert(0, self.active_provider)
            
        for p in priority:
            if p in self.providers and p not in exclude:
                return self.providers[p]
        
        # 3. Last resort: any available that is not excluded
        for p_type, config in self.providers.items():
            if p_type not in exclude:
                return config

        return {"type": "none", "error": f"No providers available (excluded: {exclude})"}

    def add_provider(self, p_type: str, api_key: str, model: str = None):
        env_key = f"{p_type.upper()}_API_KEY"
        keychain_key = KeychainManager.key_for_env(env_key) or env_key.lower()
        keychain.set_key(keychain_key, api_key)
        self._load_providers()
        return True

# Global instance
model_orchestrator = ModelOrchestrator()
