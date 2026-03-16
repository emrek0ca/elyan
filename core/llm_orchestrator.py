"""
LLM Orchestrator - Advanced Multi-Provider LLM Management

Coordinates multiple LLM providers (Groq, Gemini, Claude, GPT-4, Ollama).
Implements automatic provider selection, fallback chains, consensus mode,
and budget enforcement.

Turkish/English support with cost tracking and quality metrics.
"""

import asyncio
import time
import json
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import httpx

from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("llm_orchestrator")


class LLMProvider(Enum):
    """Supported LLM providers"""
    GROQ = "groq"
    GEMINI = "gemini"
    CLAUDE = "claude"
    GPT4 = "gpt4"
    OLLAMA = "ollama"


@dataclass
class ProviderConfig:
    """Configuration for LLM provider"""
    provider: LLMProvider
    api_key: Optional[str]
    endpoint: Optional[str]
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: int = 30
    enabled: bool = True


@dataclass
class ProviderStats:
    """Statistics for provider performance"""
    provider: LLMProvider
    model: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    quality_score: float = 0.5  # 0.0-1.0
    error_log: List[Tuple[datetime, str]] = field(default_factory=list)
    last_used: Optional[datetime] = None

    def success_rate(self) -> float:
        """Calculate success rate"""
        total = self.total_calls
        return self.successful_calls / total if total > 0 else 0.5

    def cost_per_token(self) -> float:
        """Calculate cost per token"""
        if self.total_tokens_used == 0:
            return 0.0
        return self.total_cost_usd / self.total_tokens_used

    def efficiency_score(self) -> float:
        """Composite score: quality * success_rate / (latency * cost)"""
        latency_factor = max(0.1, self.avg_latency_ms / 1000)  # Normalize to seconds
        cost_factor = max(0.001, self.cost_per_token() * 1000)  # Normalize
        return (self.quality_score * self.success_rate()) / (latency_factor * cost_factor)


@dataclass
class LLMResponse:
    """Structured LLM response"""
    content: str
    provider: LLMProvider
    model: str
    tokens_used: int
    cost_usd: float
    latency_ms: float
    quality_score: float
    error: Optional[str] = None


class CostTracker:
    """Track token usage and costs across providers"""

    def __init__(self):
        self.daily_cost: float = 0.0
        self.monthly_cost: float = 0.0
        self.daily_limit_usd: float = 50.0
        self.monthly_limit_usd: float = 500.0
        self.cost_per_token: Dict[Tuple[LLMProvider, str], float] = {
            (LLMProvider.GROQ, "llama-3.3-70b-versatile"): 0.00000140,
            (LLMProvider.GEMINI, "gemini-2.0-flash"): 0.0000001875,  # Very cheap
            (LLMProvider.CLAUDE, "claude-3-5-sonnet"): 0.0000030,
            (LLMProvider.GPT4, "gpt-4o"): 0.0000030,
            (LLMProvider.OLLAMA, "any"): 0.0,  # Local, free
        }
        self._reset_date = datetime.now().date()
        self._reset_month = datetime.now().month

    def update_daily_cost(self) -> None:
        """Reset daily cost if day changed"""
        today = datetime.now().date()
        if today != self._reset_date:
            self.daily_cost = 0.0
            self._reset_date = today

    def update_monthly_cost(self) -> None:
        """Reset monthly cost if month changed"""
        now = datetime.now()
        if now.month != self._reset_month:
            self.monthly_cost = 0.0
            self._reset_month = now.month

    def calculate_cost(
        self,
        provider: LLMProvider,
        model: str,
        tokens: int
    ) -> float:
        """Calculate cost for tokens"""
        key = (provider, model)
        cost_per_token = self.cost_per_token.get(key)
        if cost_per_token is None:
            # Fallback for unknown models
            cost_per_token = 0.0000020
        return tokens * cost_per_token

    def check_budget(self, estimated_cost: float) -> bool:
        """Check if cost would exceed limits"""
        self.update_daily_cost()
        self.update_monthly_cost()

        if self.daily_cost + estimated_cost > self.daily_limit_usd:
            logger.warning(f"Daily budget exceeded: ${self.daily_cost + estimated_cost:.2f}")
            return False

        if self.monthly_cost + estimated_cost > self.monthly_limit_usd:
            logger.warning(f"Monthly budget exceeded: ${self.monthly_cost + estimated_cost:.2f}")
            return False

        return True

    def record_cost(self, cost: float) -> None:
        """Record actual cost"""
        self.daily_cost += cost
        self.monthly_cost += cost


class QualityRanker:
    """Rank providers by output quality"""

    @staticmethod
    def score_response(
        response: str,
        expected_format: Optional[str] = None
    ) -> float:
        """Score response quality (0.0-1.0)"""
        score = 0.5  # Baseline

        # Check for completeness
        if len(response.strip()) > 50:
            score += 0.1
        if len(response.strip()) > 200:
            score += 0.1

        # Check for format compliance
        if expected_format == "json":
            try:
                json.loads(response)
                score += 0.2
            except:
                score -= 0.2
        elif expected_format == "markdown":
            if any(marker in response for marker in ["##", "- ", "**", "`"]):
                score += 0.1

        # Check for obvious errors
        if "error" in response.lower() or "failed" in response.lower():
            score -= 0.1

        return max(0.0, min(1.0, score))


class LLMOrchestrator:
    """
    Multi-LLM orchestration system.

    Features:
    - Automatic provider selection based on cost/quality/latency
    - Fallback chains (automatic retry on different provider)
    - Consensus mode (multiple LLMs, pick best response)
    - Budget enforcement
    - Quality metrics per provider
    """

    def __init__(self):
        self.providers: Dict[LLMProvider, ProviderStats] = {}
        self.configs: Dict[LLMProvider, ProviderConfig] = {}
        self.cost_tracker = CostTracker()
        self.quality_ranker = QualityRanker()

        # Fallback order: Groq (free) -> Gemini (free) -> Claude -> GPT-4 -> Ollama (free)
        self.fallback_chain = [
            LLMProvider.GROQ,
            LLMProvider.GEMINI,
            LLMProvider.OLLAMA,
            LLMProvider.CLAUDE,
            LLMProvider.GPT4,
        ]

        self._initialize_providers()
        self._load_configs()

        logger.info("LLM Orchestrator initialized")

    def _initialize_providers(self) -> None:
        """Initialize provider stats"""
        for provider in LLMProvider:
            self.providers[provider] = ProviderStats(
                provider=provider,
                model=self._get_default_model(provider)
            )

    def _get_default_model(self, provider: LLMProvider) -> str:
        """Get default model for provider"""
        defaults = {
            LLMProvider.GROQ: "llama-3.3-70b-versatile",
            LLMProvider.GEMINI: "gemini-2.0-flash",
            LLMProvider.CLAUDE: "claude-3-5-sonnet-20241022",
            LLMProvider.GPT4: "gpt-4o",
            LLMProvider.OLLAMA: "llama2",
        }
        return defaults.get(provider, "")

    def _load_configs(self) -> None:
        """Load provider configs from elyan_config"""
        # Groq
        if api_key := elyan_config.get("models.providers.groq.apiKey") or \
                      elyan_config.get("GROQ_API_KEY"):
            self.configs[LLMProvider.GROQ] = ProviderConfig(
                provider=LLMProvider.GROQ,
                api_key=api_key,
                endpoint="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile"
            )

        # Gemini
        if api_key := elyan_config.get("models.providers.google.apiKey") or \
                      elyan_config.get("GEMINI_API_KEY"):
            self.configs[LLMProvider.GEMINI] = ProviderConfig(
                provider=LLMProvider.GEMINI,
                api_key=api_key,
                endpoint="https://generativelanguage.googleapis.com/v1beta/models",
                model="gemini-2.0-flash"
            )

        # Claude
        if api_key := elyan_config.get("models.providers.anthropic.apiKey") or \
                      elyan_config.get("ANTHROPIC_API_KEY"):
            self.configs[LLMProvider.CLAUDE] = ProviderConfig(
                provider=LLMProvider.CLAUDE,
                api_key=api_key,
                endpoint="https://api.anthropic.com/v1",
                model="claude-3-5-sonnet-20241022"
            )

        # GPT-4
        if api_key := elyan_config.get("models.providers.openai.apiKey") or \
                      elyan_config.get("OPENAI_API_KEY"):
            self.configs[LLMProvider.GPT4] = ProviderConfig(
                provider=LLMProvider.GPT4,
                api_key=api_key,
                endpoint="https://api.openai.com/v1",
                model="gpt-4o"
            )

        # Ollama (local, always available)
        self.configs[LLMProvider.OLLAMA] = ProviderConfig(
            provider=LLMProvider.OLLAMA,
            api_key=None,
            endpoint="http://localhost:11434",
            model="llama2"
        )

    def select_provider(
        self,
        priority: str = "cost"  # "cost", "quality", "speed", "balanced"
    ) -> Optional[LLMProvider]:
        """Select best provider based on criteria"""
        enabled = [p for p in self.providers
                   if self.configs.get(p) and self.configs[p].enabled]
        if not enabled:
            logger.warning("No enabled providers available")
            return None

        if priority == "cost":
            # Prefer free providers: Groq, Gemini, Ollama
            free_providers = [LLMProvider.GROQ, LLMProvider.GEMINI, LLMProvider.OLLAMA]
            for p in free_providers:
                if p in enabled:
                    return p

        elif priority == "quality":
            # Sort by quality score
            sorted_providers = sorted(
                enabled,
                key=lambda p: self.providers[p].quality_score,
                reverse=True
            )
            return sorted_providers[0] if sorted_providers else None

        elif priority == "speed":
            # Sort by latency
            sorted_providers = sorted(
                enabled,
                key=lambda p: self.providers[p].avg_latency_ms
            )
            return sorted_providers[0] if sorted_providers else None

        else:  # balanced
            # Sort by efficiency score
            sorted_providers = sorted(
                enabled,
                key=lambda p: self.providers[p].efficiency_score(),
                reverse=True
            )
            return sorted_providers[0] if sorted_providers else None

    async def call_provider(
        self,
        provider: LLMProvider,
        prompt: str,
        **kwargs
    ) -> Optional[LLMResponse]:
        """Call specific provider"""
        config = self.configs.get(provider)
        if not config or not config.enabled:
            logger.error(f"Provider {provider.value} not configured or disabled")
            return None

        start_time = time.time()

        try:
            # This is a placeholder - actual implementation would use provider-specific APIs
            logger.debug(f"Calling {provider.value} with model {config.model}")

            # Simulate API call
            await asyncio.sleep(0.1)

            response_text = f"Response from {provider.value}"
            tokens_used = len(prompt.split()) * 2  # Rough estimate
            latency_ms = (time.time() - start_time) * 1000

            # Calculate cost
            cost = self.cost_tracker.calculate_cost(provider, config.model, tokens_used)

            # Score quality
            quality = self.quality_ranker.score_response(response_text)

            # Update stats
            stats = self.providers[provider]
            stats.total_calls += 1
            stats.successful_calls += 1
            stats.total_tokens_used += tokens_used
            stats.total_cost_usd += cost
            stats.avg_latency_ms = (
                (stats.avg_latency_ms * (stats.total_calls - 1) + latency_ms) /
                stats.total_calls
            )
            stats.quality_score = (
                (stats.quality_score * (stats.total_calls - 1) + quality) /
                stats.total_calls
            )
            stats.last_used = datetime.now()

            # Check budget
            if not self.cost_tracker.check_budget(cost):
                logger.warning(f"Budget limit would be exceeded: ${cost:.4f}")
                return None

            self.cost_tracker.record_cost(cost)

            return LLMResponse(
                content=response_text,
                provider=provider,
                model=config.model,
                tokens_used=tokens_used,
                cost_usd=cost,
                latency_ms=latency_ms,
                quality_score=quality
            )

        except Exception as e:
            logger.error(f"Error calling {provider.value}: {e}")
            stats = self.providers[provider]
            stats.failed_calls += 1
            stats.error_log.append((datetime.now(), str(e)))
            if len(stats.error_log) > 100:
                stats.error_log.pop(0)
            return None

    async def call_with_fallback(
        self,
        prompt: str,
        priority: str = "cost"
    ) -> Optional[LLMResponse]:
        """Call provider with automatic fallback"""
        providers = self.fallback_chain.copy()

        # Sort by priority
        if priority == "quality":
            providers.sort(
                key=lambda p: self.providers[p].quality_score,
                reverse=True
            )
        elif priority == "speed":
            providers.sort(
                key=lambda p: self.providers[p].avg_latency_ms
            )

        for provider in providers:
            response = await self.call_provider(provider, prompt)
            if response:
                return response

        logger.error("All providers failed")
        return None

    async def call_consensus(
        self,
        prompt: str,
        num_providers: int = 3
    ) -> Optional[Dict[str, Any]]:
        """Call multiple providers and return best response"""
        # Select top providers by efficiency
        sorted_providers = sorted(
            self.providers.keys(),
            key=lambda p: self.providers[p].efficiency_score(),
            reverse=True
        )[:num_providers]

        responses: List[LLMResponse] = []
        tasks = [self.call_provider(p, prompt) for p in sorted_providers]

        for task in asyncio.as_completed(tasks):
            response = await task
            if response:
                responses.append(response)

        if not responses:
            logger.error("Consensus mode: no responses received")
            return None

        # Sort by quality score
        best_response = max(responses, key=lambda r: r.quality_score)

        return {
            "content": best_response.content,
            "provider": best_response.provider.value,
            "quality_score": best_response.quality_score,
            "num_responses": len(responses),
            "avg_quality": sum(r.quality_score for r in responses) / len(responses),
            "total_cost": sum(r.cost_usd for r in responses)
        }

    def get_provider_stats(self, provider: LLMProvider) -> ProviderStats:
        """Get statistics for provider"""
        return self.providers[provider]

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all providers"""
        return {
            p.value: {
                "total_calls": self.providers[p].total_calls,
                "success_rate": f"{self.providers[p].success_rate():.1%}",
                "avg_latency_ms": f"{self.providers[p].avg_latency_ms:.0f}",
                "total_cost": f"${self.providers[p].total_cost_usd:.2f}",
                "quality_score": f"{self.providers[p].quality_score:.1f}",
                "efficiency_score": f"{self.providers[p].efficiency_score():.2f}"
            }
            for p in LLMProvider
        }

    def set_budget_limits(self, daily: float, monthly: float) -> None:
        """Set daily and monthly budget limits"""
        self.cost_tracker.daily_limit_usd = daily
        self.cost_tracker.monthly_limit_usd = monthly
        logger.info(f"Budget limits set: ${daily}/day, ${monthly}/month")


# Singleton instance
_orchestrator: Optional[LLMOrchestrator] = None


def get_llm_orchestrator() -> LLMOrchestrator:
    """Get or create orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = LLMOrchestrator()
    return _orchestrator
