"""
API Rate Limiter - Rate limiting and SLA enforcement for API endpoints
Provides token bucket, sliding window, and adaptive rate limiting strategies
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class RateLimitStrategy(Enum):
    """Rate limiting strategies"""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    ADAPTIVE = "adaptive"


@dataclass
class RateLimit:
    """Rate limit configuration"""
    name: str
    requests_per_minute: int
    burst_size: int = 0  # Allow burst requests
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET

    def __post_init__(self):
        if self.burst_size == 0:
            self.burst_size = self.requests_per_minute


@dataclass
class RateLimitViolation:
    """Rate limit violation record"""
    client_id: str
    endpoint: str
    timestamp: float
    retry_after_seconds: int = 60
    severity: str = "warning"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SLAMetric:
    """SLA metric tracking"""
    endpoint: str
    response_time_p95_ms: float
    response_time_p99_ms: float
    uptime_percentage: float
    error_rate: float
    availability: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TokenBucket:
    """Token bucket rate limiter"""

    def __init__(self, capacity: float, refill_rate: float):
        """
        Args:
            capacity: Max tokens (burst size)
            refill_rate: Tokens per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.RLock()

    def allow_request(self, tokens_required: float = 1.0) -> bool:
        """Check if request is allowed"""
        with self.lock:
            self._refill()
            if self.tokens >= tokens_required:
                self.tokens -= tokens_required
                return True
            return False

    def get_wait_time(self, tokens_required: float = 1.0) -> float:
        """Get time to wait for tokens"""
        with self.lock:
            self._refill()
            if self.tokens >= tokens_required:
                return 0.0
            tokens_needed = tokens_required - self.tokens
            return tokens_needed / self.refill_rate

    def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now


class SlidingWindow:
    """Sliding window rate limiter"""

    def __init__(self, window_size_seconds: int, max_requests: int):
        self.window_size = window_size_seconds
        self.max_requests = max_requests
        self.requests: deque = deque()
        self.lock = threading.RLock()

    def allow_request(self) -> bool:
        """Check if request is allowed"""
        with self.lock:
            now = time.time()
            cutoff = now - self.window_size

            # Remove old requests
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()

            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False

    def get_wait_time(self) -> float:
        """Get time to wait until next request allowed"""
        with self.lock:
            if not self.requests:
                return 0.0
            oldest = self.requests[0]
            return max(0.0, oldest + self.window_size - time.time())


class AdaptiveRateLimiter:
    """Adaptive rate limiter based on system load"""

    def __init__(self, initial_rps: float, min_rps: float = 1.0, max_rps: float = 100.0):
        self.current_rps = initial_rps
        self.min_rps = min_rps
        self.max_rps = max_rps
        self.last_adjustment = time.time()
        self.lock = threading.RLock()
        self.bucket = TokenBucket(initial_rps, initial_rps)

    def adjust_rate(self, error_rate: float, response_time_ms: float):
        """Adjust rate based on system metrics"""
        with self.lock:
            now = time.time()
            if now - self.last_adjustment < 1.0:
                return

            adjustment = 1.0
            if error_rate > 0.05:  # >5% errors
                adjustment = 0.9  # Reduce by 10%
            elif response_time_ms > 1000:  # >1s response
                adjustment = 0.95  # Reduce by 5%
            elif error_rate < 0.01 and response_time_ms < 100:  # Good health
                adjustment = 1.05  # Increase by 5%

            new_rps = max(self.min_rps, min(self.max_rps, self.current_rps * adjustment))
            if new_rps != self.current_rps:
                self.current_rps = new_rps
                self.bucket = TokenBucket(new_rps, new_rps)
                logger.info(f"Rate limit adjusted to {new_rps:.2f} RPS")

            self.last_adjustment = now

    def allow_request(self) -> bool:
        return self.bucket.allow_request()


class RateLimitManager:
    """Centralized rate limit management"""

    def __init__(self):
        self.limiters: Dict[str, Dict] = {}
        self.violations: deque = deque(maxlen=10000)
        self.lock = threading.RLock()
        self.client_buckets: Dict[str, TokenBucket] = {}

    def add_limit(self, client_id: str, limit: RateLimit):
        """Add rate limit for client"""
        with self.lock:
            if client_id not in self.limiters:
                self.limiters[client_id] = {}

            if limit.strategy == RateLimitStrategy.TOKEN_BUCKET:
                capacity = limit.burst_size
                refill_rate = limit.requests_per_minute / 60.0
                limiter = TokenBucket(capacity, refill_rate)
            elif limit.strategy == RateLimitStrategy.SLIDING_WINDOW:
                limiter = SlidingWindow(60, limit.requests_per_minute)
            else:  # ADAPTIVE
                limiter = AdaptiveRateLimiter(limit.requests_per_minute / 60.0)

            self.limiters[client_id][limit.name] = {
                "config": limit,
                "limiter": limiter
            }

    def check_limit(self, client_id: str, endpoint: str) -> Tuple[bool, Optional[int]]:
        """
        Check if request is allowed
        Returns: (allowed, retry_after_seconds)
        """
        with self.lock:
            if client_id not in self.limiters:
                return True, None

            endpoint_limit = self.limiters[client_id].get(endpoint)
            if not endpoint_limit:
                return True, None

            limiter = endpoint_limit["limiter"]

            if isinstance(limiter, (TokenBucket, SlidingWindow)):
                if limiter.allow_request():
                    return True, None
                wait_time = int(limiter.get_wait_time()) + 1
            else:  # AdaptiveRateLimiter
                if limiter.allow_request():
                    return True, None
                wait_time = 60

            # Record violation
            violation = RateLimitViolation(
                client_id=client_id,
                endpoint=endpoint,
                timestamp=time.time(),
                retry_after_seconds=wait_time
            )
            self.violations.append(violation)

            return False, wait_time

    def record_metrics(self, client_id: str, endpoint: str,
                      error_rate: float, response_time_ms: float):
        """Record metrics for adaptive limiting"""
        with self.lock:
            if client_id not in self.limiters:
                return

            limiter_info = self.limiters[client_id].get(endpoint)
            if not limiter_info:
                return

            limiter = limiter_info["limiter"]
            if isinstance(limiter, AdaptiveRateLimiter):
                limiter.adjust_rate(error_rate, response_time_ms)

    def get_violations(self, client_id: Optional[str] = None,
                       limit: int = 100) -> List[Dict]:
        """Get rate limit violations"""
        with self.lock:
            violations = list(self.violations)
            if client_id:
                violations = [v for v in violations if v.client_id == client_id]
            return [v.to_dict() for v in violations[-limit:]]

    def get_client_limits(self, client_id: str) -> Dict[str, Any]:
        """Get all limits for a client"""
        with self.lock:
            if client_id not in self.limiters:
                return {}

            result = {}
            for endpoint, limit_info in self.limiters[client_id].items():
                result[endpoint] = {
                    "requests_per_minute": limit_info["config"].requests_per_minute,
                    "burst_size": limit_info["config"].burst_size,
                    "strategy": limit_info["config"].strategy.value
                }
            return result


class SLAEnforcer:
    """Enforce SLA requirements"""

    def __init__(self):
        self.endpoint_metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.sla_targets: Dict[str, Dict] = {}
        self.violations: deque = deque(maxlen=1000)
        self.lock = threading.RLock()

    def set_sla_target(self, endpoint: str, p95_ms: float, p99_ms: float,
                       uptime_pct: float, error_rate: float):
        """Set SLA targets for endpoint"""
        with self.lock:
            self.sla_targets[endpoint] = {
                "p95_ms": p95_ms,
                "p99_ms": p99_ms,
                "uptime_pct": uptime_pct,
                "error_rate": error_rate
            }

    def record_request(self, endpoint: str, response_time_ms: float,
                       success: bool):
        """Record request metrics"""
        with self.lock:
            self.endpoint_metrics[endpoint].append({
                "timestamp": time.time(),
                "response_time_ms": response_time_ms,
                "success": success
            })

    def check_sla(self, endpoint: str) -> Dict[str, Any]:
        """Check if SLA is being met"""
        with self.lock:
            if endpoint not in self.endpoint_metrics:
                return {"error": "No data"}

            metrics = list(self.endpoint_metrics[endpoint])
            if not metrics:
                return {"error": "No data"}

            target = self.sla_targets.get(endpoint, {})
            if not target:
                return {"error": "No SLA target"}

            # Calculate metrics
            times = sorted([m["response_time_ms"] for m in metrics])
            n = len(times)
            p95 = times[int(n * 0.95)] if n > 0 else 0
            p99 = times[int(n * 0.99)] if n > 0 else 0
            success_count = sum(1 for m in metrics if m["success"])
            uptime = (success_count / len(metrics) * 100) if metrics else 0
            error_rate = 1 - (success_count / len(metrics)) if metrics else 0

            violations = []
            if p95 > target.get("p95_ms", float("inf")):
                violations.append(f"P95 latency {p95}ms exceeds {target['p95_ms']}ms")
            if p99 > target.get("p99_ms", float("inf")):
                violations.append(f"P99 latency {p99}ms exceeds {target['p99_ms']}ms")
            if uptime < target.get("uptime_pct", 100):
                violations.append(f"Uptime {uptime}% below {target['uptime_pct']}%")
            if error_rate > target.get("error_rate", 0.01):
                violations.append(f"Error rate {error_rate:.2%} exceeds {target['error_rate']:.2%}")

            return {
                "endpoint": endpoint,
                "timestamp": datetime.now().isoformat(),
                "metrics": {
                    "p95_ms": p95,
                    "p99_ms": p99,
                    "uptime_percentage": uptime,
                    "error_rate": error_rate,
                    "request_count": len(metrics)
                },
                "targets": target,
                "compliant": len(violations) == 0,
                "violations": violations
            }

    def get_all_sla_status(self) -> Dict[str, Any]:
        """Get SLA status for all endpoints"""
        with self.lock:
            status = {}
            for endpoint in self.sla_targets.keys():
                status[endpoint] = self.check_sla(endpoint)
            return status


class APIRateLimiter:
    """Main API rate limiter"""

    def __init__(self):
        self.rate_manager = RateLimitManager()
        self.sla_enforcer = SLAEnforcer()
        self.lock = threading.RLock()

    def configure_client(self, client_id: str, limits: List[RateLimit]):
        """Configure rate limits for client"""
        for limit in limits:
            self.rate_manager.add_limit(client_id, limit)

    def check_request(self, client_id: str, endpoint: str) -> Tuple[bool, Optional[int]]:
        """Check if request is allowed"""
        return self.rate_manager.check_limit(client_id, endpoint)

    def record_request(self, client_id: str, endpoint: str,
                      response_time_ms: float, success: bool):
        """Record request for tracking"""
        self.sla_enforcer.record_request(endpoint, response_time_ms, success)
        # Could calculate error_rate and record metrics here

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status"""
        return {
            "timestamp": datetime.now().isoformat(),
            "sla_status": self.sla_enforcer.get_all_sla_status(),
            "recent_violations": self.rate_manager.get_violations(limit=20)
        }

    def __repr__(self) -> str:
        return "<APIRateLimiter>"
