"""
Performance Profiler & Optimizer
Deep performance analysis, bottleneck detection, automatic optimization
"""

import time
import psutil
import functools
import tracemalloc
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
import statistics

from utils.logger import get_logger

logger = get_logger("performance_profiler")


@dataclass
class FunctionProfile:
    """Profile data for a function"""
    name: str
    call_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    avg_time: float = 0.0
    memory_usage: List[float] = field(default_factory=list)
    call_stack_depth: int = 0


@dataclass
class Bottleneck:
    """Identified performance bottleneck"""
    function_name: str
    issue_type: str  # slow_execution, high_memory, frequent_calls
    severity: str  # low, medium, high, critical
    metric_value: float
    suggestion: str


class PerformanceProfiler:
    """
    Performance Profiler & Optimizer
    - Function execution profiling
    - Memory usage tracking
    - Bottleneck detection
    - Optimization suggestions
    - Performance comparison
    - Automatic optimization
    """

    def __init__(self):
        self.profiles: Dict[str, FunctionProfile] = {}
        self.execution_history: deque = deque(maxlen=1000)
        self.bottlenecks: List[Bottleneck] = []
        self.profiling_active = False
        self.memory_tracking = False

        # Thresholds
        self.slow_threshold_ms = 1000  # 1 second
        self.frequent_call_threshold = 100
        self.high_memory_threshold_mb = 100

        logger.info("Performance Profiler initialized")

    def profile(self, func: Callable) -> Callable:
        """Decorator to profile a function"""
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not self.profiling_active:
                return await func(*args, **kwargs)

            func_name = f"{func.__module__}.{func.__name__}"

            # Start profiling
            start_time = time.time()

            # Track memory if enabled
            if self.memory_tracking:
                tracemalloc.start()

            try:
                result = await func(*args, **kwargs)
                success = True
                error = None
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                # Calculate duration
                duration = (time.time() - start_time) * 1000  # ms

                # Track memory
                memory_mb = 0
                if self.memory_tracking:
                    current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    memory_mb = peak / 1024 / 1024

                # Update profile
                self._update_profile(func_name, duration, memory_mb)

                # Record execution
                self.execution_history.append({
                    "function": func_name,
                    "duration_ms": duration,
                    "memory_mb": memory_mb,
                    "timestamp": time.time(),
                    "success": success,
                    "error": error
                })

            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not self.profiling_active:
                return func(*args, **kwargs)

            func_name = f"{func.__module__}.{func.__name__}"

            start_time = time.time()

            if self.memory_tracking:
                tracemalloc.start()

            try:
                result = func(*args, **kwargs)
                success = True
                error = None
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration = (time.time() - start_time) * 1000

                memory_mb = 0
                if self.memory_tracking:
                    current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    memory_mb = peak / 1024 / 1024

                self._update_profile(func_name, duration, memory_mb)

                self.execution_history.append({
                    "function": func_name,
                    "duration_ms": duration,
                    "memory_mb": memory_mb,
                    "timestamp": time.time(),
                    "success": success,
                    "error": error
                })

            return result

        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    def _update_profile(self, func_name: str, duration_ms: float, memory_mb: float):
        """Update function profile"""
        if func_name not in self.profiles:
            self.profiles[func_name] = FunctionProfile(name=func_name)

        profile = self.profiles[func_name]
        profile.call_count += 1
        profile.total_time += duration_ms
        profile.min_time = min(profile.min_time, duration_ms)
        profile.max_time = max(profile.max_time, duration_ms)
        profile.avg_time = profile.total_time / profile.call_count

        if memory_mb > 0:
            profile.memory_usage.append(memory_mb)

    def start_profiling(self, track_memory: bool = False):
        """Start profiling"""
        self.profiling_active = True
        self.memory_tracking = track_memory
        logger.info("Profiling started" + (" (with memory tracking)" if track_memory else ""))

    def stop_profiling(self):
        """Stop profiling"""
        self.profiling_active = False
        self.memory_tracking = False
        logger.info("Profiling stopped")

    def analyze_bottlenecks(self) -> List[Bottleneck]:
        """Analyze and identify bottlenecks"""
        self.bottlenecks.clear()

        for func_name, profile in self.profiles.items():
            # Check for slow execution
            if profile.avg_time > self.slow_threshold_ms:
                severity = "critical" if profile.avg_time > 5000 else "high" if profile.avg_time > 2000 else "medium"

                self.bottlenecks.append(Bottleneck(
                    function_name=func_name,
                    issue_type="slow_execution",
                    severity=severity,
                    metric_value=profile.avg_time,
                    suggestion=f"Average execution time {profile.avg_time:.0f}ms is too slow. Consider optimization."
                ))

            # Check for frequent calls
            if profile.call_count > self.frequent_call_threshold:
                severity = "high" if profile.call_count > 1000 else "medium"

                self.bottlenecks.append(Bottleneck(
                    function_name=func_name,
                    issue_type="frequent_calls",
                    severity=severity,
                    metric_value=profile.call_count,
                    suggestion=f"Called {profile.call_count} times. Consider caching or batching."
                ))

            # Check for high memory usage
            if profile.memory_usage:
                avg_memory = statistics.mean(profile.memory_usage)
                if avg_memory > self.high_memory_threshold_mb:
                    severity = "critical" if avg_memory > 500 else "high"

                    self.bottlenecks.append(Bottleneck(
                        function_name=func_name,
                        issue_type="high_memory",
                        severity=severity,
                        metric_value=avg_memory,
                        suggestion=f"Average memory usage {avg_memory:.1f}MB is high. Check for memory leaks."
                    ))

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.bottlenecks.sort(key=lambda b: severity_order.get(b.severity, 999))

        logger.info(f"Identified {len(self.bottlenecks)} bottlenecks")
        return self.bottlenecks

    def get_optimization_suggestions(self) -> List[str]:
        """Get optimization suggestions based on profiling data"""
        suggestions = []

        # Analyze bottlenecks
        self.analyze_bottlenecks()

        for bottleneck in self.bottlenecks[:10]:  # Top 10
            suggestions.append(f"[{bottleneck.severity.upper()}] {bottleneck.function_name}: {bottleneck.suggestion}")

        # Overall system suggestions
        total_executions = sum(p.call_count for p in self.profiles.values())
        if total_executions > 10000:
            suggestions.append("High number of total executions. Consider request batching.")

        # Check for similar functions
        func_names = list(self.profiles.keys())
        for i, name1 in enumerate(func_names):
            for name2 in func_names[i+1:]:
                if self._functions_similar(name1, name2):
                    suggestions.append(f"Similar functions detected: {name1} and {name2}. Consider consolidation.")

        return suggestions

    def _functions_similar(self, name1: str, name2: str) -> bool:
        """Check if two function names are similar"""
        # Simple similarity check
        import difflib
        similarity = difflib.SequenceMatcher(None, name1, name2).ratio()
        return similarity > 0.7

    def compare_performance(
        self,
        func_name: str,
        baseline_avg_ms: float
    ) -> Dict[str, Any]:
        """Compare current performance against baseline"""
        if func_name not in self.profiles:
            return {"error": "Function not profiled"}

        profile = self.profiles[func_name]
        current_avg = profile.avg_time

        improvement = ((baseline_avg_ms - current_avg) / baseline_avg_ms * 100) if baseline_avg_ms > 0 else 0

        return {
            "function": func_name,
            "baseline_ms": baseline_avg_ms,
            "current_ms": current_avg,
            "improvement_percent": improvement,
            "status": "faster" if improvement > 0 else "slower" if improvement < 0 else "same"
        }

    def get_top_slow_functions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get slowest functions"""
        sorted_profiles = sorted(
            self.profiles.values(),
            key=lambda p: p.avg_time,
            reverse=True
        )

        return [
            {
                "function": p.name,
                "avg_time_ms": p.avg_time,
                "max_time_ms": p.max_time,
                "call_count": p.call_count,
                "total_time_ms": p.total_time
            }
            for p in sorted_profiles[:limit]
        ]

    def get_top_frequent_functions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most frequently called functions"""
        sorted_profiles = sorted(
            self.profiles.values(),
            key=lambda p: p.call_count,
            reverse=True
        )

        return [
            {
                "function": p.name,
                "call_count": p.call_count,
                "avg_time_ms": p.avg_time,
                "total_time_ms": p.total_time
            }
            for p in sorted_profiles[:limit]
        ]

    def get_memory_hogs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get functions with highest memory usage"""
        memory_profiles = [
            (p.name, statistics.mean(p.memory_usage))
            for p in self.profiles.values()
            if p.memory_usage
        ]

        memory_profiles.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "function": name,
                "avg_memory_mb": mem_mb,
                "peak_memory_mb": max(self.profiles[name].memory_usage)
            }
            for name, mem_mb in memory_profiles[:limit]
        ]

    def reset_profiles(self):
        """Clear all profiling data"""
        self.profiles.clear()
        self.execution_history.clear()
        self.bottlenecks.clear()
        logger.info("Profiling data reset")

    def export_report(self, file_path: str):
        """Export profiling report"""
        report = {
            "summary": self.get_summary(),
            "bottlenecks": [
                {
                    "function": b.function_name,
                    "type": b.issue_type,
                    "severity": b.severity,
                    "value": b.metric_value,
                    "suggestion": b.suggestion
                }
                for b in self.bottlenecks
            ],
            "top_slow": self.get_top_slow_functions(20),
            "top_frequent": self.get_top_frequent_functions(20),
            "memory_hogs": self.get_memory_hogs(20) if self.memory_tracking else []
        }

        with open(file_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Exported profiling report to {file_path}")

    def get_summary(self) -> Dict[str, Any]:
        """Get profiling summary"""
        total_calls = sum(p.call_count for p in self.profiles.values())
        total_time = sum(p.total_time for p in self.profiles.values())

        return {
            "profiled_functions": len(self.profiles),
            "total_calls": total_calls,
            "total_time_ms": total_time,
            "bottlenecks_detected": len(self.bottlenecks),
            "profiling_active": self.profiling_active,
            "memory_tracking": self.memory_tracking
        }


# Global instance
_performance_profiler: Optional[PerformanceProfiler] = None


def get_performance_profiler() -> PerformanceProfiler:
    """Get or create global performance profiler instance"""
    global _performance_profiler
    if _performance_profiler is None:
        _performance_profiler = PerformanceProfiler()
    return _performance_profiler
