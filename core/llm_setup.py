"""
LLM Setup & Provider Manager

Tek merkezden LLM provider yönetimi:
- API key kaydetme/silme/test etme
- Provider durumu sorgulama
- Ollama model yönetimi (liste/indir/sil)
- Otomatik fallback zinciri
- İlk kurulum sihirbazı desteği

Hiçbir durumda hata fırlatmaz — her zaman graceful sonuç döner.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from utils.logger import get_logger

logger = get_logger("llm_setup")

# ── Provider Definitions ───────────────────────────────────────

PROVIDERS = {
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "test_endpoint": "https://api.groq.com/openai/v1/models",
        "signup_url": "https://console.groq.com/keys",
        "default_model": "llama-3.3-70b-versatile",
        "free": True,
        "description": "Ücretsiz, çok hızlı. Başlangıç için ideal.",
    },
    "google": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "test_endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "signup_url": "https://aistudio.google.com/apikey",
        "default_model": "gemini-2.0-flash",
        "free": True,
        "description": "Ücretsiz, güçlü. Groq alternatifi.",
    },
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "test_endpoint": "https://api.openai.com/v1/models",
        "signup_url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-4o",
        "free": False,
        "description": "Ücretli ama en güçlü modellerden biri.",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "env_key": "ANTHROPIC_API_KEY",
        "test_endpoint": "https://api.anthropic.com/v1/models",
        "signup_url": "https://console.anthropic.com/settings/keys",
        "default_model": "claude-sonnet-4-20250514",
        "free": False,
        "description": "Ücretli, kod ve analiz için çok iyi.",
    },
    "ollama": {
        "name": "Ollama (Lokal)",
        "env_key": None,
        "test_endpoint": "http://localhost:11434/api/tags",
        "signup_url": "https://ollama.ai/download",
        "default_model": "llama3.2:3b",
        "free": True,
        "description": "Ücretsiz, tamamen lokal. İnternet gerektirmez.",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "test_endpoint": "https://api.deepseek.com/models",
        "signup_url": "https://platform.deepseek.com/api_keys",
        "default_model": "deepseek-chat",
        "free": False,
        "description": "Uygun fiyatlı, kod için güçlü.",
    },
}

# Recommended models for Ollama (small → large)
OLLAMA_RECOMMENDED_MODELS = [
    {"name": "llama3.2:3b", "size": "2.0 GB", "description": "Hızlı, hafif. Basit görevler için."},
    {"name": "mistral:latest", "size": "4.1 GB", "description": "Dengeli. Genel kullanım."},
    {"name": "qwen2.5-coder:7b", "size": "4.7 GB", "description": "Kod yazma uzmanı."},
    {"name": "llama3.1:8b", "size": "4.7 GB", "description": "Güçlü, çok yönlü."},
    {"name": "llava:7b", "size": "4.7 GB", "description": "Görsel anlama (vision) desteği."},
]


# ── Data Models ────────────────────────────────────────────────

@dataclass
class ProviderStatus:
    """A provider's current status."""
    provider: str
    name: str
    configured: bool = False
    reachable: bool = False
    api_key_set: bool = False
    key_source: str = ""  # "config", "env", "keychain", "none"
    model: str = ""
    error: str = ""
    latency_ms: float = 0.0
    free: bool = True
    description: str = ""
    signup_url: str = ""


@dataclass
class OllamaModel:
    """An Ollama model entry."""
    name: str
    size: str = ""
    modified: str = ""
    digest: str = ""
    installed: bool = False


# ── LLM Setup Manager ─────────────────────────────────────────

class LLMSetupManager:
    """
    Central LLM provider management.
    Never throws exceptions — always returns structured results.
    """

    def __init__(self):
        self._config_dir = Path.home() / ".elyan"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._setup_flag = self._config_dir / ".setup_complete"

    # ── Setup Status ───────────────────────────────────────────

    def is_first_run(self) -> bool:
        """Check if this is the first run (no setup done yet)."""
        return not self._setup_flag.exists()

    def mark_setup_complete(self):
        """Mark initial setup as done."""
        self._setup_flag.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))

    # ── Provider Status ────────────────────────────────────────

    async def get_all_provider_status(self) -> List[Dict[str, Any]]:
        """Get status of all providers. Never throws."""
        results = []
        tasks = [self._check_provider(name) for name in PROVIDERS]
        statuses = await asyncio.gather(*tasks, return_exceptions=True)
        for status in statuses:
            if isinstance(status, Exception):
                results.append({"provider": "unknown", "error": str(status)})
            else:
                results.append(asdict(status))
        return results

    async def get_provider_status(self, provider: str) -> Dict[str, Any]:
        """Get status of a single provider."""
        try:
            status = await self._check_provider(provider)
            return asdict(status)
        except Exception as e:
            return {"provider": provider, "error": str(e)}

    async def _check_provider(self, provider: str) -> ProviderStatus:
        """Check a single provider's status."""
        info = PROVIDERS.get(provider, {})
        status = ProviderStatus(
            provider=provider,
            name=info.get("name", provider),
            free=info.get("free", False),
            description=info.get("description", ""),
            signup_url=info.get("signup_url", ""),
        )

        # Check API key
        if provider == "ollama":
            status.api_key_set = True  # No key needed
            status.key_source = "not_required"
        else:
            key, source = self._find_api_key(provider)
            status.api_key_set = bool(key)
            status.key_source = source

        # Check model
        status.model = self._get_configured_model(provider)

        # Check reachability
        try:
            status.configured = status.api_key_set
            start = time.time()
            reachable = await self._test_provider_connection(provider)
            status.latency_ms = (time.time() - start) * 1000
            status.reachable = reachable
        except Exception as e:
            status.error = str(e)[:100]

        return status

    def _find_api_key(self, provider: str) -> Tuple[str, str]:
        """Find API key from all sources. Returns (key, source)."""
        info = PROVIDERS.get(provider, {})
        env_key = info.get("env_key", "")

        if not env_key:
            return "", "not_required"

        # 1. Environment variable
        val = os.environ.get(env_key, "")
        if val:
            return val, "env"

        # 2. Elyan config
        try:
            from config.elyan_config import elyan_config
            config_val = elyan_config.get(f"models.providers.{provider}.apiKey", "")
            if config_val and not config_val.startswith("$"):
                return config_val, "config"
        except Exception:
            pass

        # 3. Keychain
        try:
            from core.keychain_manager import keychain
            kc_key = env_key.lower()
            kc_val = keychain.get_key(kc_key)
            if kc_val:
                return kc_val, "keychain"
        except Exception:
            pass

        return "", "none"

    def _get_configured_model(self, provider: str) -> str:
        """Get configured model for provider."""
        try:
            from config.elyan_config import elyan_config
            model = elyan_config.get(f"models.providers.{provider}.model", "")
            if model:
                return model
        except Exception:
            pass
        return PROVIDERS.get(provider, {}).get("default_model", "")

    async def _test_provider_connection(self, provider: str) -> bool:
        """Test if provider is reachable."""
        info = PROVIDERS.get(provider, {})
        url = info.get("test_endpoint", "")
        if not url:
            return False

        try:
            headers = {}
            if provider != "ollama":
                key, _ = self._find_api_key(provider)
                if not key:
                    return False
                if provider == "openai":
                    headers["Authorization"] = f"Bearer {key}"
                elif provider == "groq":
                    headers["Authorization"] = f"Bearer {key}"
                elif provider in ("google", "gemini"):
                    url = f"{url}?key={key}"
                elif provider == "anthropic":
                    headers["x-api-key"] = key
                    headers["anthropic-version"] = "2023-06-01"
                elif provider == "deepseek":
                    headers["Authorization"] = f"Bearer {key}"

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
                return resp.status_code in (200, 401, 403)  # 401/403 = key issue but reachable
        except Exception:
            return False

    # ── API Key Management ─────────────────────────────────────

    async def save_api_key(self, provider: str, api_key: str) -> Dict[str, Any]:
        """Save API key and test it. Returns status."""
        info = PROVIDERS.get(provider)
        if not info:
            return {"success": False, "error": f"Bilinmeyen provider: {provider}"}

        if provider == "ollama":
            return {"success": True, "message": "Ollama için API key gerekmez."}

        api_key = api_key.strip()
        if not api_key:
            return {"success": False, "error": "API key boş olamaz."}

        # Save to keychain + config
        try:
            from core.model_orchestrator import model_orchestrator
            model_orchestrator.add_provider(provider, api_key)
        except Exception as e:
            logger.warning(f"Orchestrator save failed, using direct save: {e}")
            # Direct save fallback
            try:
                env_key = info.get("env_key", "")
                os.environ[env_key] = api_key
                from config.elyan_config import elyan_config
                elyan_config.set(f"models.providers.{provider}.apiKey", api_key)
            except Exception as e2:
                return {"success": False, "error": f"Key kaydetme hatası: {e2}"}

        # Also set env for current session
        env_key = info.get("env_key", "")
        if env_key:
            os.environ[env_key] = api_key

        # Test connection
        reachable = await self._test_provider_connection(provider)
        if reachable:
            return {
                "success": True,
                "message": f"{info['name']} bağlantısı başarılı!",
                "provider": provider,
                "reachable": True,
            }
        else:
            return {
                "success": True,
                "message": f"Key kaydedildi ama bağlantı test edilemedi. Key'i kontrol et.",
                "provider": provider,
                "reachable": False,
            }

    async def remove_api_key(self, provider: str) -> Dict[str, Any]:
        """Remove API key for a provider."""
        info = PROVIDERS.get(provider)
        if not info or provider == "ollama":
            return {"success": False, "error": "Bu provider için key kaldırılamaz."}

        env_key = info.get("env_key", "")
        os.environ.pop(env_key, None)

        try:
            from config.elyan_config import elyan_config
            elyan_config.set(f"models.providers.{provider}.apiKey", "")
        except Exception:
            pass

        try:
            from core.keychain_manager import keychain
            keychain.set_key(env_key.lower(), "")
        except Exception:
            pass

        return {"success": True, "message": f"{info['name']} API key kaldırıldı."}

    # ── Ollama Management ──────────────────────────────────────

    async def ollama_status(self) -> Dict[str, Any]:
        """Check Ollama status and installed models."""
        result = {
            "running": False,
            "models": [],
            "recommended": OLLAMA_RECOMMENDED_MODELS,
            "install_url": "https://ollama.ai/download",
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    result["running"] = True
                    data = resp.json()
                    installed_names = set()
                    for m in data.get("models", []):
                        name = m.get("name", "")
                        installed_names.add(name)
                        size_bytes = m.get("size", 0)
                        size_str = f"{size_bytes / (1024**3):.1f} GB" if size_bytes else ""
                        result["models"].append({
                            "name": name,
                            "size": size_str,
                            "modified": m.get("modified_at", ""),
                            "digest": m.get("digest", "")[:12],
                            "installed": True,
                        })

                    # Mark recommended as installed/not
                    for rec in result["recommended"]:
                        rec["installed"] = rec["name"] in installed_names
        except Exception:
            pass

        return result

    async def ollama_pull_model(self, model_name: str) -> Dict[str, Any]:
        """Pull (download) an Ollama model."""
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    "http://localhost:11434/api/pull",
                    json={"name": model_name, "stream": False},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": f"'{model_name}' başarıyla indirildi."}
                else:
                    return {"success": False, "error": f"İndirme hatası: {resp.status_code}"}
        except httpx.TimeoutException:
            return {"success": False, "error": "İndirme zaman aşımına uğradı. Model çok büyük olabilir."}
        except httpx.ConnectError:
            return {"success": False, "error": "Ollama çalışmıyor. Önce 'ollama serve' komutunu çalıştır."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def ollama_delete_model(self, model_name: str) -> Dict[str, Any]:
        """Delete an Ollama model."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    "http://localhost:11434/api/delete",
                    json={"name": model_name},
                )
                if resp.status_code == 200:
                    return {"success": True, "message": f"'{model_name}' silindi."}
                else:
                    return {"success": False, "error": f"Silme hatası: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Quick Health Check ─────────────────────────────────────

    async def quick_health(self) -> Dict[str, Any]:
        """Quick health check — which providers work right now?"""
        statuses = await self.get_all_provider_status()
        working = [s for s in statuses if s.get("reachable")]
        configured = [s for s in statuses if s.get("configured")]

        return {
            "any_working": len(working) > 0,
            "working_count": len(working),
            "working_providers": [s["provider"] for s in working],
            "configured_count": len(configured),
            "total_providers": len(PROVIDERS),
            "needs_setup": len(working) == 0,
            "providers": statuses,
        }

    # ── Setup Recommendation ───────────────────────────────────

    def get_setup_recommendation(self) -> Dict[str, Any]:
        """Get recommended setup steps for new users."""
        return {
            "steps": [
                {
                    "step": 1,
                    "title": "En Kolay: Groq (Ücretsiz)",
                    "description": "1 dakikada ücretsiz API key al",
                    "url": "https://console.groq.com/keys",
                    "provider": "groq",
                },
                {
                    "step": 2,
                    "title": "Alternatif: Google Gemini (Ücretsiz)",
                    "description": "Google hesabınla ücretsiz key al",
                    "url": "https://aistudio.google.com/apikey",
                    "provider": "google",
                },
                {
                    "step": 3,
                    "title": "Lokal: Ollama (İnternetsiz)",
                    "description": "Bilgisayarında çalışır, veri dışarı çıkmaz",
                    "url": "https://ollama.ai/download",
                    "provider": "ollama",
                },
            ],
            "note": "En az 1 provider ayarlanmalı. Groq en hızlı başlangıçtır.",
        }


# ── Singleton ──────────────────────────────────────────────────

_llm_setup: Optional[LLMSetupManager] = None


def get_llm_setup() -> LLMSetupManager:
    global _llm_setup
    if _llm_setup is None:
        _llm_setup = LLMSetupManager()
    return _llm_setup
