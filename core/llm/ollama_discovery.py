"""
core/llm/ollama_discovery.py
───────────────────────────────────────────────────────────────────────────────
Ollama Auto-Discovery & Health Check

Periodically probes the local Ollama API to:
  1. Discover which models are pulled and ready
  2. Update ModelSelectionPolicy availability flags
  3. Provide a health status for the runtime dashboard

Design:
  - Non-blocking: uses aiohttp with short timeouts
  - Graceful: if Ollama isn't running, all local models marked unavailable
  - Singleton with start/stop lifecycle
"""

from __future__ import annotations

import asyncio
from typing import Any

from utils.logger import get_logger

logger = get_logger("ollama_discovery")

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
_PROBE_INTERVAL_S = 30
_TIMEOUT_S = 5


class OllamaDiscovery:
    """Discovers local Ollama models and keeps availability in sync."""

    def __init__(self, base_url: str = _DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._running = False
        self._task: asyncio.Task | None = None
        self._available_models: list[str] = []
        self._healthy = False

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def available_models(self) -> list[str]:
        return list(self._available_models)

    async def probe_once(self) -> list[str]:
        """Single probe: fetch available models from Ollama API.

        Returns list of model names (e.g. ["llama3.2:3b", "qwen2.5:7b"]).
        """
        try:
            import aiohttp
        except ImportError:
            logger.debug("aiohttp not available, skipping Ollama probe")
            self._healthy = False
            return []

        try:
            timeout = aiohttp.ClientTimeout(total=_TIMEOUT_S)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    if resp.status != 200:
                        self._healthy = False
                        self._available_models = []
                        return []
                    data = await resp.json()
        except Exception:
            self._healthy = False
            self._available_models = []
            return []

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if name:
                models.append(name)

        self._healthy = True
        self._available_models = models
        return models

    async def sync_with_policy(self) -> None:
        """Probe Ollama and update ModelSelectionPolicy availability."""
        discovered = await self.probe_once()
        discovered_set = set(discovered)

        try:
            from core.llm.model_selection_policy import get_model_selection_policy
            policy = get_model_selection_policy()
        except Exception:
            return

        for candidate in policy._candidates:
            if candidate.provider != "ollama":
                continue
            # Match by model name (exact or prefix)
            is_available = any(
                candidate.model == d or d.startswith(candidate.model.split(":")[0])
                for d in discovered_set
            )
            policy.set_availability("ollama", candidate.model, is_available)

        if discovered:
            logger.info(f"Ollama: {len(discovered)} models available: {discovered}")
        else:
            logger.debug("Ollama: no models available or service unreachable")

    async def start(self) -> None:
        """Start periodic background discovery."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Ollama discovery started")

    async def stop(self) -> None:
        """Stop discovery loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.sync_with_policy()
            except Exception as exc:
                logger.debug(f"Ollama discovery error: {exc}")
            await asyncio.sleep(_PROBE_INTERVAL_S)

    def status(self) -> dict[str, Any]:
        return {
            "healthy": self._healthy,
            "base_url": self.base_url,
            "models": list(self._available_models),
            "model_count": len(self._available_models),
        }


# ── Singleton ───────────────────────────────────────────────────────────────

_instance: OllamaDiscovery | None = None


def get_ollama_discovery() -> OllamaDiscovery:
    global _instance
    if _instance is None:
        _instance = OllamaDiscovery()
    return _instance


__all__ = ["OllamaDiscovery", "get_ollama_discovery"]
