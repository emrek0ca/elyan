"""
Elyan Circuit Breaker — Prevents cascading failures by stopping requests to failing providers.

States:
- CLOSED: Everything normal, requests pass.
- OPEN: Failure threshold reached, requests blocked for a cooling period.
- HALF_OPEN: Testing if provider has recovered with a limited number of requests.
"""

import time
from enum import Enum
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("circuit_breaker")

class State(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreaker:
    def __init__(
        self, 
        failure_threshold: int = 3, 
        recovery_timeout: int = 60,
        half_open_max_requests: int = 2
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests
        
        self.state = State.CLOSED
        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_requests = 0

    def can_execute(self) -> bool:
        """Check if request can be executed based on state."""
        if self.state == State.CLOSED:
            return True
        
        if self.state == State.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = State.HALF_OPEN
                self.half_open_requests = 0
                logger.info("Circuit breaker entering HALF_OPEN state.")
                return True
            return False
        
        if self.state == State.HALF_OPEN:
            if self.half_open_requests < self.half_open_max_requests:
                self.half_open_requests += 1
                return True
            return False
            
        return False

    def record_success(self):
        """Record a successful call to close the circuit."""
        if self.state == State.HALF_OPEN:
            self.state = State.CLOSED
            self.failures = 0
            logger.info("Circuit breaker restored to CLOSED state.")
        elif self.state == State.CLOSED:
            self.failures = 0

    def record_failure(self):
        """Record a failure to potentially open the circuit."""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.state == State.CLOSED and self.failures >= self.failure_threshold:
            self.state = State.OPEN
            logger.warning(f"Circuit breaker OPENED after {self.failures} failures.")
        elif self.state == State.HALF_OPEN:
            self.state = State.OPEN
            logger.warning("Circuit breaker RE-OPENED during HALF_OPEN phase.")

class ProviderResilienceManager:
    """Manages circuit breakers for multiple LLM providers."""
    
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}

    def get_breaker(self, provider: str) -> CircuitBreaker:
        if provider not in self.breakers:
            self.breakers[provider] = CircuitBreaker()
        return self.breakers[provider]

    def can_call(self, provider: str) -> bool:
        return self.get_breaker(provider).can_execute()

    def record_success(self, provider: str):
        self.get_breaker(provider).record_success()

    def record_failure(self, provider: str):
        self.get_breaker(provider).record_failure()

    def get_all_states(self) -> Dict[str, str]:
        """Return a mapping of provider names to their circuit breaker state."""
        return {p: b.state.value for p, b in self.breakers.items()}

# Global instance
resilience_manager = ProviderResilienceManager()
