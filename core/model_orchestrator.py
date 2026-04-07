import os
from typing import Any, Dict, List, Optional

from config.elyan_config import elyan_config
from core.accuracy_speed_runtime import get_accuracy_speed_runtime
from core.model_catalog import default_model_for_provider, normalize_model_name
from core.neural_router import neural_router
from security.keychain import KeychainManager, keychain
from utils.ollama_helper import OllamaHelper
from utils.logger import get_logger

logger = get_logger("model_orchestrator")


_PROVIDER_ALIASES = {
    "gemini": "google",
    "api": "google",
    "local": "ollama",
}
_KNOWN_PROVIDERS = ("openai", "anthropic", "google", "groq", "ollama", "deepseek", "mistral", "together", "cohere", "perplexity", "xai")
_COLLAB_ROLE_DEFAULTS = [
    "reasoning",
    "planning",
    "code",
    "critic",
    "qa",
    "research_worker",
    "code_worker",
]


class ModelOrchestrator:
    def __init__(self):
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.registry: List[Dict[str, Any]] = []
        self.active_provider = self._normalize_provider(
            elyan_config.get("models.default.provider", "ollama") or "ollama"
        )
        self.metrics: Dict[str, Dict[str, Any]] = {}
        self._load_providers()

    @staticmethod
    def _local_first_enabled() -> bool:
        return bool(elyan_config.get("agent.model.local_first", True))

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        raw = str(provider or "").strip().lower()
        return _PROVIDER_ALIASES.get(raw, raw)

    def record_metric(self, provider: str, success: bool, latency: float):
        provider_name = self._normalize_provider(provider)
        if provider_name not in self.metrics:
            self.metrics[provider_name] = {"success": 0, "failure": 0, "latencies": []}

        m = self.metrics[provider_name]
        if success:
            m["success"] += 1
        else:
            m["failure"] += 1

        m["latencies"].append(latency)
        if len(m["latencies"]) > 50:
            m["latencies"].pop(0)

    def get_health_report(self) -> Dict[str, Any]:
        report = {}
        for provider, metrics in self.metrics.items():
            total = metrics["success"] + metrics["failure"]
            rate = (metrics["success"] / total * 100) if total > 0 else 0
            avg_latency = sum(metrics["latencies"]) / len(metrics["latencies"]) if metrics["latencies"] else 0
            report[provider] = {
                "success_rate": f"{rate:.1f}%",
                "avg_latency": f"{avg_latency:.3f}s",
                "total_calls": total,
                "status": self.providers.get(provider, {}).get("status", "unknown"),
            }
        return report

    def _load_from_keychain(self, provider: str) -> Optional[str]:
        provider_name = self._normalize_provider(provider)
        env_key = f"{provider_name.upper()}_API_KEY"
        val = os.getenv(env_key)
        if val:
            return val
        return keychain.get_key(KeychainManager.key_for_env(env_key) or env_key.lower())

    def _normalize_model_for_provider(self, provider: str, model: Optional[str]) -> str:
        provider_name = self._normalize_provider(provider)
        model = (model or "").strip()
        if not model:
            return default_model_for_provider(provider_name)
        low = model.lower()
        if "/" in model and not low.startswith(("http://", "https://")):
            pref_provider, pref_model = model.split("/", 1)
            if self._normalize_provider(pref_provider) == provider_name:
                model = pref_model.strip()
                low = model.lower()
        if provider_name == "openai":
            return model if low.startswith(("gpt-", "o1", "o3", "gpt4")) else default_model_for_provider(provider_name)
        if provider_name == "anthropic":
            return model if "claude" in low else default_model_for_provider(provider_name)
        if provider_name == "google":
            return model if "gemini" in low else default_model_for_provider(provider_name)
        if provider_name == "groq":
            return model if low.startswith(("llama", "mixtral", "qwen", "deepseek")) else default_model_for_provider(provider_name)
        return normalize_model_name(provider_name, model)

    def _ensure_provider_runtime(self, provider: str) -> bool:
        provider_name = self._normalize_provider(provider)
        if provider_name != "ollama":
            return True
        try:
            return OllamaHelper.ensure_available(allow_install=True, start_service=True)
        except Exception as exc:
            logger.debug(f"Ollama runtime ensure failed: {exc}")
            return False

    def _provider_default_config(self, provider: str) -> Dict[str, Any]:
        provider_name = self._normalize_provider(provider)
        cfg = elyan_config.get(f"models.providers.{provider_name}", {}) or {}
        if provider_name == "google" and not cfg:
            cfg = elyan_config.get("models.providers.gemini", {}) or {}
        default_cfg = elyan_config.get("models.default", {}) or {}
        fallback_cfg = elyan_config.get("models.fallback", {}) or {}
        local_cfg = elyan_config.get("models.local", {}) or {}
        endpoint = cfg.get("endpoint") or cfg.get("baseUrl")
        if provider_name == "ollama":
            endpoint = endpoint or local_cfg.get("baseUrl") or "http://localhost:11434"
        api_key = cfg.get("apiKey") or (None if provider_name == "ollama" else self._load_from_keychain(provider_name))
        candidate_model = (
            cfg.get("default_model")
            or cfg.get("model")
            or (default_cfg.get("model") if self._normalize_provider(default_cfg.get("provider")) == provider_name else None)
            or (fallback_cfg.get("model") if self._normalize_provider(fallback_cfg.get("provider")) == provider_name else None)
            or (local_cfg.get("model") if provider_name == "ollama" else None)
            or default_model_for_provider(provider_name)
        )
        return {
            "type": provider_name,
            "provider": provider_name,
            "model": self._normalize_model_for_provider(provider_name, candidate_model),
            "apiKey": api_key,
            "endpoint": endpoint,
        }

    def _normalize_roles(self, roles: Any) -> List[str]:
        if not isinstance(roles, list):
            return []
        normalized: List[str] = []
        for role in roles:
            role_name = str(role or "").strip().lower()
            if role_name and role_name not in normalized:
                normalized.append(role_name)
        return normalized

    def _build_registry_entry(self, raw: Dict[str, Any], *, source: str = "registry") -> Optional[Dict[str, Any]]:
        provider = self._normalize_provider(raw.get("provider") or raw.get("type"))
        if provider not in _KNOWN_PROVIDERS:
            return None
        defaults = self._provider_default_config(provider)
        model = self._normalize_model_for_provider(provider, raw.get("model") or defaults.get("model"))
        alias = str(raw.get("alias") or raw.get("name") or "").strip()
        entry_id = str(raw.get("id") or f"{provider}:{model}").strip()
        enabled = bool(raw.get("enabled", True))
        roles = self._normalize_roles(raw.get("roles"))
        priority_raw = raw.get("priority", 50)
        try:
            priority = max(0, min(999, int(priority_raw)))
        except Exception:
            priority = 50
        api_key = raw.get("apiKey") or defaults.get("apiKey")
        endpoint = raw.get("endpoint") or defaults.get("endpoint")
        available = bool(provider == "ollama" or api_key)
        status = "configured" if available else "missing_credentials"
        if not enabled:
            status = "disabled"
        return {
            "id": entry_id,
            "alias": alias,
            "label": alias or f"{provider}/{model}",
            "provider": provider,
            "type": provider,
            "model": model,
            "apiKey": api_key,
            "endpoint": endpoint,
            "enabled": enabled,
            "available": available,
            "status": status,
            "roles": roles,
            "priority": priority,
            "source": source,
        }

    def _dedupe_registry(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        out: List[Dict[str, Any]] = []
        for item in items:
            key = str(item.get("id") or f"{item.get('provider')}:{item.get('model')}")
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _load_providers(self):
        self.providers = {}
        self.registry = []
        default_cfg = elyan_config.get("models.default", {}) or {}
        fallback_cfg = elyan_config.get("models.fallback", {}) or {}
        local_cfg = elyan_config.get("models.local", {}) or {}
        registry_cfg = elyan_config.get("models.registry", []) or []
        if not isinstance(registry_cfg, list):
            registry_cfg = []

        for provider in _KNOWN_PROVIDERS:
            config = self._provider_default_config(provider)
            if provider == "ollama" or config.get("apiKey"):
                config["status"] = "configured"
                self.providers[provider] = config

        synthesized: List[Dict[str, Any]] = []
        synthesized.append(
            {
                "id": "default",
                "provider": default_cfg.get("provider") or "openai",
                "model": default_cfg.get("model"),
                "alias": "Default",
                "enabled": True,
                "priority": 5,
            }
        )
        synthesized.append(
            {
                "id": "fallback",
                "provider": fallback_cfg.get("provider") or "openai",
                "model": fallback_cfg.get("model"),
                "alias": "Fallback",
                "enabled": True,
                "priority": 15,
            }
        )
        synthesized.append(
            {
                "id": "local",
                "provider": local_cfg.get("provider") or "ollama",
                "model": local_cfg.get("model"),
                "alias": "Local",
                "enabled": True,
                "roles": ["router", "inference"],
                "priority": 10,
            }
        )

        loaded: List[Dict[str, Any]] = []
        for item in list(registry_cfg) + synthesized:
            if not isinstance(item, dict):
                continue
            entry = self._build_registry_entry(item, source="registry")
            if entry:
                loaded.append(entry)

        if not loaded:
            for provider, data in self.providers.items():
                entry = self._build_registry_entry(
                    {
                        "id": f"{provider}:{data.get('model')}",
                        "provider": provider,
                        "model": data.get("model"),
                        "enabled": True,
                    },
                    source="provider",
                )
                if entry:
                    loaded.append(entry)

        self.registry = self._dedupe_registry(loaded)
        logger.info("Loaded providers=%s registry=%s", list(self.providers.keys()), len(self.registry))

    def get_collaboration_settings(self) -> Dict[str, Any]:
        cfg = elyan_config.get("models.collaboration", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        try:
            max_models = int(cfg.get("max_models", 3) or 3)
        except Exception:
            max_models = 3
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "strategy": str(cfg.get("strategy", "synthesize") or "synthesize").strip().lower(),
            "max_models": max(1, min(5, max_models)),
            "roles": self._normalize_roles(cfg.get("roles")) or list(_COLLAB_ROLE_DEFAULTS),
        }

    def list_registered_models(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        items = []
        for item in self.registry:
            if enabled_only and not bool(item.get("enabled")):
                continue
            payload = {k: v for k, v in item.items() if k != "apiKey"}
            payload["has_api_key"] = bool(item.get("apiKey")) if item.get("provider") != "ollama" else True
            items.append(payload)
        return items

    def get_provider_config(self, provider: str, role: str = "inference", model: Optional[str] = None) -> Dict[str, Any]:
        provider_name = self._normalize_provider(provider)
        cfg = dict(self.providers.get(provider_name) or self._provider_default_config(provider_name))
        cfg["type"] = provider_name
        cfg["provider"] = provider_name
        if model:
            cfg["model"] = self._normalize_model_for_provider(provider_name, model)
        return cfg

    def find_provider_for_model(self, model: str) -> Optional[str]:
        target = str(model or "").strip().lower()
        if not target:
            return None
        if "/" in target:
            provider, _ = target.split("/", 1)
            return self._normalize_provider(provider)
        for item in self.registry:
            if str(item.get("model") or "").strip().lower() == target:
                return str(item.get("provider") or "").strip().lower()
        return None

    def resolve_model_hint(self, model_hint: str, role: str = "inference") -> Dict[str, Any]:
        raw = str(model_hint or "").strip()
        if not raw:
            return self.get_best_available(role)
        provider = self.find_provider_for_model(raw)
        model = raw
        if "/" in raw and not raw.lower().startswith(("http://", "https://")):
            maybe_provider, maybe_model = raw.split("/", 1)
            provider = self._normalize_provider(maybe_provider)
            model = maybe_model.strip()
        if not provider:
            return self.get_best_available(role)
        return self.get_provider_config(provider, role=role, model=model)

    def rank_candidates(self, role: str = "inference", exclude: set | None = None) -> List[Dict[str, Any]]:
        role_name = str(role or "inference").strip().lower() or "inference"
        excluded = {self._normalize_provider(item) for item in (exclude or set())}
        provider_priority = {
            self._normalize_provider(provider): idx
            for idx, provider in enumerate(self._priority_for_role(role_name))
        }
        try:
            preferred = neural_router.get_model_for_role(role_name) or {}
        except Exception as e:
            logger.debug(f"Neural router preference lookup failed for role '{role_name}': {e}")
            preferred = {}
        pref_provider = self._normalize_provider(preferred.get("provider") or preferred.get("type"))
        pref_model = str(preferred.get("model") or "").strip().lower()
        pref_rank = provider_priority.get(pref_provider, 99)
        collab = self.get_collaboration_settings()
        ranked: List[tuple[tuple[Any, ...], Dict[str, Any]]] = []
        seen_keys: set[str] = set()
        for entry in self.registry:
            provider = self._normalize_provider(entry.get("provider") or entry.get("type"))
            if provider in excluded:
                continue
            if not bool(entry.get("enabled")):
                continue
            roles = self._normalize_roles(entry.get("roles"))
            if roles and role_name not in roles:
                continue
            provider_cfg = self.providers.get(provider) or {}
            provider_configured = bool(provider_cfg) and str(provider_cfg.get("status", "configured")) != "disabled"
            if not provider_configured and not bool(entry.get("apiKey")):
                continue
            role_match = True
            score = 0
            # Neural router preference bonus only for "router" role (fast local).
            # For inference/code/etc., rely on _priority_for_role quality ordering.
            pref_bonus_allowed = role_name == "router" or pref_rank <= 1
            if pref_provider and provider == pref_provider and pref_bonus_allowed:
                score += 100
            if pref_model and str(entry.get("model") or "").strip().lower() == pref_model and pref_bonus_allowed:
                score += 120
            if role_match:
                score += 30
            if role_name in collab["roles"]:
                score += 10
            if self._local_first_enabled() and provider == "ollama":
                score += 120
            score += max(0, 25 - (provider_priority.get(provider, 99) * 5))
            success_rate = 0.0
            metrics = self.metrics.get(provider) or {}
            total = int(metrics.get("success", 0)) + int(metrics.get("failure", 0))
            if total > 0:
                success_rate = float(metrics.get("success", 0)) / total
                score += int(success_rate * 20)
            score -= min(10, int(entry.get("priority", 50)) // 10)
            seen_keys.add(f"{provider}:{str(entry.get('model') or '').strip().lower()}")
            ranked.append(((-score, int(entry.get("priority", 50)), provider, str(entry.get("model") or "")), entry))

        # Providers may be updated programmatically in tests/runtime without rebuilding registry.
        # Synthesize missing candidates from current provider state so role-aware fallback remains correct.
        for provider, provider_cfg in self.providers.items():
            provider_name = self._normalize_provider(provider)
            if provider_name in excluded:
                continue
            model_name = str(provider_cfg.get("model") or "").strip()
            key = f"{provider_name}:{model_name.lower()}"
            if key in seen_keys:
                continue
            entry = {
                "id": key,
                "provider": provider_name,
                "type": provider_name,
                "model": model_name,
                "enabled": True,
                "priority": 50,
                "roles": [],
            }
            score = 30 + max(0, 25 - (provider_priority.get(provider_name, 99) * 5))
            ranked.append(((-score, 50, provider_name, model_name), entry))
        ranked.sort(key=lambda item: item[0])
        return [dict(item[1]) for item in ranked]

    def get_collaboration_pool(
        self,
        role: str = "reasoning",
        *,
        max_models: Optional[int] = None,
        exclude: set | None = None,
    ) -> List[Dict[str, Any]]:
        collab = self.get_collaboration_settings()
        pool_limit = max_models if max_models is not None else collab["max_models"]
        candidates = self.rank_candidates(role=role, exclude=exclude)
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for entry in candidates:
            key = f"{entry.get('provider')}:{entry.get('model')}"
            if key in seen:
                continue
            seen.add(key)
            out.append(self.get_provider_config(str(entry.get("provider") or ""), role=role, model=str(entry.get("model") or "")) | {
                "id": entry.get("id"),
                "alias": entry.get("alias"),
                "roles": list(entry.get("roles") or []),
                "priority": entry.get("priority", 50),
            })
            if len(out) >= pool_limit:
                break
        return out

    def get_collaboration_profile(
        self,
        *,
        text: str,
        role: str = "reasoning",
        request_kind: str = "chat",
        provider_lane: str = "",
        has_attachments: bool = False,
    ) -> Dict[str, Any]:
        runtime = get_accuracy_speed_runtime()
        collab = self.get_collaboration_settings()
        decision = runtime.recommend_collaboration(
            text=text,
            request_kind=request_kind,
            role=role,
            provider_lane=provider_lane,
            has_attachments=has_attachments,
        )
        enabled = bool(collab.get("enabled", True)) and bool(decision.enabled)
        max_models = 1 if not enabled else min(int(collab.get("max_models", 3) or 3), int(decision.max_models or 1))
        return {
            "enabled": enabled,
            "strategy": str(decision.strategy or collab.get("strategy") or "synthesize"),
            "max_models": max(1, max_models),
            "synthesis_role": str(decision.synthesis_role or role or "reasoning"),
            "execution_style": str(decision.execution_style or "single_pass"),
            "lenses": list(decision.lenses or []),
        }

    def get_best_available(self, role: str = "inference", exclude: set = None) -> Dict[str, Any]:
        ranked = self.rank_candidates(role=role, exclude=exclude)
        if ranked:
            top = ranked[0]
            config = self.get_provider_config(
                str(top.get("provider") or ""),
                role=role,
                model=str(top.get("model") or ""),
            )
            if self._normalize_provider(config.get("provider") or "") == "ollama" and not self._ensure_provider_runtime(config.get("provider") or ""):
                config["status"] = "missing_runtime"
            return config

        role_name = str(role or "inference").strip().lower() or "inference"
        priority = self._priority_for_role(role_name)
        # Only prepend active_provider for "router" role (fast local classification).
        # For all other roles, trust the quality-optimised priority list.
        if role_name == "router" and self.active_provider not in priority[:1]:
            priority = [self.active_provider] + [p for p in priority if p != self.active_provider]
        excluded = {self._normalize_provider(item) for item in (exclude or set())}
        for provider in priority:
            provider_name = self._normalize_provider(provider)
            if provider_name in self.providers and provider_name not in excluded:
                config = dict(self.providers[provider_name])
                if provider_name == "ollama" and not self._ensure_provider_runtime(provider_name):
                    config["status"] = "missing_runtime"
                return config

        for provider_name, config in self.providers.items():
            if provider_name not in excluded:
                resolved = dict(config)
                if provider_name == "ollama" and not self._ensure_provider_runtime(provider_name):
                    resolved["status"] = "missing_runtime"
                return resolved
        return {"type": "none", "error": f"No providers available (excluded: {exclude})"}

    def get_best_for_lane(self, provider_lane: str, *, role: str = "inference", exclude: set | None = None) -> Dict[str, Any]:
        runtime = get_accuracy_speed_runtime()
        preferred_order = runtime.provider_order(provider_lane, local_first=self._local_first_enabled())
        excluded = {self._normalize_provider(item) for item in (exclude or set())}
        candidates = self.rank_candidates(role=role, exclude=excluded)
        for provider_name in preferred_order:
            for item in candidates:
                candidate_provider = self._normalize_provider(item.get("provider") or item.get("type"))
                if candidate_provider != provider_name:
                    continue
                return self.get_provider_config(candidate_provider, role=role, model=str(item.get("model") or ""))
        return self.get_best_available(role=role, exclude=exclude)

    def _priority_for_role(self, role: str) -> List[str]:
        """Return provider priority order for a given role.

        When local-first is enabled, Ollama is preferred first for all roles
        and cloud providers remain as fallback. Otherwise the historical
        quality-first ordering is preserved.
        """
        role_name = str(role or "inference").strip().lower()
        local_first = self._local_first_enabled()

        cloud_order = ["groq", "google", "openai", "anthropic", "deepseek", "mistral", "together"]
        local_order = ["ollama"]

        if role_name == "router":
            return local_order + cloud_order
        if role_name in {"code", "code_worker"}:
            if local_first:
                return local_order + ["groq", "deepseek", "google", "anthropic", "openai", "mistral", "together"]
            return ["groq", "deepseek", "google", "anthropic", "openai", "mistral", "together", "ollama"]
        if role_name in {"reasoning", "research_worker", "worker", "critic", "planning", "qa"}:
            if local_first:
                return local_order + ["groq", "google", "deepseek", "anthropic", "openai", "mistral", "together"]
            return ["groq", "google", "deepseek", "anthropic", "openai", "mistral", "together", "ollama"]
        if role_name == "creative":
            if local_first:
                return local_order + ["google", "groq", "anthropic", "openai", "mistral", "together", "deepseek"]
            return ["google", "groq", "anthropic", "openai", "mistral", "together", "deepseek", "ollama"]
        if local_first:
            return local_order + cloud_order
        # inference / default — quality first
        return ["groq", "google", "openai", "anthropic", "deepseek", "mistral", "together", "ollama"]

    def add_provider(self, p_type: str, api_key: str, model: str = None):
        provider = self._normalize_provider(p_type)
        if provider not in _KNOWN_PROVIDERS:
            raise ValueError(f"unknown_provider:{p_type}")
        env_key = f"{provider.upper()}_API_KEY"
        keychain_key = KeychainManager.key_for_env(env_key) or env_key.lower()
        if provider != "ollama":
            keychain.set_key(keychain_key, api_key)
            elyan_config.set(f"models.providers.{provider}.apiKey", f"${env_key}")
        if model:
            normalized_model = self._normalize_model_for_provider(provider, model)
            elyan_config.set(f"models.providers.{provider}.model", normalized_model)
            current_registry = elyan_config.get("models.registry", []) or []
            if not isinstance(current_registry, list):
                current_registry = []
            entry_id = f"{provider}:{normalized_model}"
            next_registry = [item for item in current_registry if str((item or {}).get("id") or "") != entry_id]
            next_registry.append(
                {
                    "id": entry_id,
                    "provider": provider,
                    "model": normalized_model,
                    "alias": f"{provider}/{normalized_model}",
                    "enabled": True,
                    "priority": 40,
                }
            )
            elyan_config.set("models.registry", next_registry)
        self._load_providers()
        return True


model_orchestrator = ModelOrchestrator()
