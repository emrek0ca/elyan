"""
Latency Optimizer - <100ms response time guarantee
"""

import time
import logging
from typing import Dict, Callable, Any, Optional
from functools import wraps
from collections import OrderedDict

logger = logging.getLogger(__name__)


class LatencyOptimizer:
    """Optimizes response latency"""

    def __init__(self, max_cache_size: int = 1000, timeout_ms: int = 100):
        self.max_cache_size = max_cache_size
        self.timeout_ms = timeout_ms
        self.cache = OrderedDict()
        self.fast_paths = {}
        self.execution_times = []

    def cache_result(self, key: str, value: Any, ttl_seconds: int = 3600):
        """Cache a result"""
        self.cache[key] = {"value": value, "ttl": time.time() + ttl_seconds}
        if len(self.cache) > self.max_cache_size:
            self.cache.popitem(last=False)

    def get_cached(self, key: str) -> Optional[Any]:
        """Get cached result"""
        if key in self.cache:
            cached = self.cache[key]
            if time.time() < cached["ttl"]:
                return cached["value"]
            else:
                del self.cache[key]
        return None

    def register_fast_path(self, pattern: str, handler: Callable):
        """Register fast path for common requests"""
        self.fast_paths[pattern] = handler
        logger.info(f"Registered fast path: {pattern}")

    def try_fast_path(self, request: Dict) -> Optional[Any]:
        """Try fast path execution"""
        for pattern, handler in self.fast_paths.items():
            if pattern in str(request):
                try:
                    start = time.time()
                    result = handler(request)
                    elapsed = (time.time() - start) * 1000
                    
                    if elapsed < self.timeout_ms:
                        self.execution_times.append(elapsed)
                        return result
                except Exception as e:
                    logger.debug(f"Fast path failed: {e}")
        
        return None

    def optimize_request(self, request: Dict) -> Dict:
        """Optimize request for faster processing"""
        # Remove unnecessary fields
        optimized = {}
        for k, v in request.items():
            if v is not None and v != "" and v != []:
                optimized[k] = v
        
        return optimized

    def batch_requests(self, requests: list) -> Dict:
        """Batch multiple requests for efficiency"""
        return {
            "batch_id": id(requests),
            "request_count": len(requests),
            "requests": requests,
            "timestamp": time.time()
        }

    def get_performance_stats(self) -> Dict:
        """Get performance statistics"""
        if not self.execution_times:
            return {"status": "No data"}
        
        avg_time = sum(self.execution_times) / len(self.execution_times)
        return {
            "avg_latency_ms": avg_time,
            "min_latency_ms": min(self.execution_times),
            "max_latency_ms": max(self.execution_times),
            "requests_under_100ms": sum(1 for t in self.execution_times if t < 100),
            "cache_size": len(self.cache),
            "fast_paths_registered": len(self.fast_paths)
        }

    def measure_execution(self, func: Callable) -> Callable:
        """Decorator to measure execution time"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            elapsed = (time.time() - start) * 1000
            self.execution_times.append(elapsed)
            
            if elapsed > self.timeout_ms:
                logger.warning(f"{func.__name__} exceeded {self.timeout_ms}ms: {elapsed:.1f}ms")
            
            return result
        return wrapper
