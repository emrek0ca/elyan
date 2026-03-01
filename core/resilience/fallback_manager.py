"""
core/resilience/fallback_manager.py
─────────────────────────────────────────────────────────────────────────────
Orchestrates LLM provider failover based on circuit breaker states and 
real-time execution errors.
"""

from typing import Dict, Any, Optional, List
from utils.logger import get_logger
from core.resilience.circuit_breaker import resilience_manager

logger = get_logger("fallback_manager")

class FallbackManager:
    """
    Manages the failover logic for LLM requests.
    If a primary provider is unavailable or fails, it selects an alternative.
    """
    
    def __init__(self):
        # Default fallback chains if not explicitly provided by the router
        self.default_chains = {
            "openai": ["anthropic", "google", "ollama"],
            "anthropic": ["openai", "google", "ollama"],
            "google": ["openai", "anthropic", "ollama"],
            "ollama": ["openai", "google"]
        }

    def get_best_provider(
        self,
        primary_provider: str,
        strategy: str = "performance",
        allowed_providers: Optional[List[str]] = None,
    ) -> str:
        """
        Returns the best available provider starting from the primary.
        Checks circuit breaker status for each.
        """
        allowed = {str(p).strip().lower() for p in (allowed_providers or []) if str(p).strip()}

        if allowed and primary_provider not in allowed:
            pass
        elif resilience_manager.can_call(primary_provider):
            return primary_provider
            
        logger.warning(f"Primary provider '{primary_provider}' is currently OPEN (failing). Searching for fallback...")
        
        chain = self.default_chains.get(primary_provider, ["ollama"])
        for fallback in chain:
            if allowed and fallback not in allowed:
                continue
            if resilience_manager.can_call(fallback):
                logger.info(f"Fallback selected: {fallback} (replacing {primary_provider})")
                return fallback
                
        logger.error("All fallback providers are also failing or unavailable.")
        return primary_provider # Return primary anyway as last resort (will fail again but logged)

    async def execute_with_fallback(
        self,
        agent,
        primary_config: Dict[str, Any],
        prompt: str,
        *,
        allowed_providers: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        """
        High-level wrapper to execute an LLM call with automatic failover.
        """
        provider = primary_config.get("provider") or primary_config.get("type") or "ollama"
        model = primary_config.get("model")
        
        # 1. Check if healthy
        if not resilience_manager.can_call(provider):
            fallback_provider = self.get_best_provider(provider, allowed_providers=allowed_providers)
            if fallback_provider != provider:
                logger.info(f"Switching to fallback provider: {fallback_provider}")
                from core.kernel import kernel
                # Temporarily use fallback for this call
                # Note: This assumes kernel.llm can handle different providers or we swap the component
                # In Elyan v20, kernel.llm is often a specific client.
                # We may need to get a new client instance from factory.
                provider = fallback_provider
                # For simplicity in this version, we assume the router handles the config swap.
                # In a more robust impl, we'd call a factory here.

        try:
            # This is a simplified placeholder for the actual LLM call logic
            # which usually resides in agent.llm.generate
            return await agent.llm.generate(prompt, model_config={"type": provider, "model": model}, **kwargs)
        except Exception as e:
            logger.error(f"Execution failed on {provider}: {e}. Triggering emergency fallback if possible.")
            resilience_manager.record_failure(provider)
            # Second attempt with fallback
            alt_provider = self.get_best_provider(provider, allowed_providers=allowed_providers)
            if alt_provider != provider:
                return await agent.llm.generate(prompt, model_config={"type": alt_provider}, **kwargs)
            raise e

# Global instance
fallback_manager = FallbackManager()
