"""
Analytics Engine - Real-time metrics and business intelligence
"""

import logging
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetric:
    """Metric for a single execution step."""
    name: str
    duration: float = 0.0
    success: bool = True
    tokens_used: int = 0
    cost: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolAnalytic:
    """Analytics for tool usage."""
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    total_duration: float = 0.0
    avg_duration: float = 0.0
    error_rate: float = 0.0
    reliability_score: float = 0.0

    @property
    def total_calls(self) -> int:
        return self.call_count

    @property
    def successful_calls(self) -> int:
        return self.success_count


@dataclass
class UserAnalytic:
    """Analytics for user interactions."""
    user_id: str
    message_count: int = 0
    session_count: int = 0
    avg_response_time: float = 0.0
    satisfaction_score: float = 0.0
    top_intents: List[str] = field(default_factory=list)
    total_interactions: int = 0
    language_preference: str = ""


@dataclass
class LLMMetric:
    """Metric for LLM provider usage."""
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_calls: int = 0
    quality_score: float = 0.0


@dataclass
class ExecutionRecord:
    tool: str
    intent: str
    duration_ms: float
    success: bool
    complexity: float = 0.0
    cost: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AnalyticsEngine:
    """Tracks and analyzes metrics"""

    def __init__(self, db_path: Any | None = None):
        self.db_path = Path(db_path).expanduser() if db_path else Path("/tmp/elyan_analytics.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.touch(exist_ok=True)
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.events: List[Dict] = []
        self.roi_data: Dict[str, Dict] = {}
        self._execution_cache: List[ExecutionRecord] = []
        self._tool_cache: Dict[str, ToolAnalytic] = {}
        self._user_cache: Dict[str, UserAnalytic] = {}
        self._llm_cache: Dict[str, Dict[str, LLMMetric]] = defaultdict(dict)
        self._flush_every = 10
        self._dirty_writes = 0
        self._load()

    def _persist(self) -> None:
        payload = {
            "metrics": {k: list(v) for k, v in self.metrics.items()},
            "events": list(self.events),
            "roi_data": dict(self.roi_data),
            "execution_cache": [record.__dict__ for record in self._execution_cache],
            "tool_cache": {k: value.__dict__ for k, value in self._tool_cache.items()},
            "user_cache": {k: value.__dict__ for k, value in self._user_cache.items()},
            "llm_cache": {
                provider: {model: metric.__dict__ for model, metric in entries.items()}
                for provider, entries in self._llm_cache.items()
            },
        }
        self.db_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        self._dirty_writes = 0

    def _persist_if_needed(self, *, force: bool = False) -> None:
        self._dirty_writes += 1
        if force or self._dirty_writes >= self._flush_every:
            self._persist()

    def _load(self) -> None:
        try:
            raw = self.db_path.read_text(encoding="utf-8").strip()
        except Exception:
            raw = ""
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        self.metrics = defaultdict(list, {k: list(v or []) for k, v in dict(payload.get("metrics") or {}).items()})
        self.events = list(payload.get("events") or [])
        self.roi_data = dict(payload.get("roi_data") or {})
        self._execution_cache = [ExecutionRecord(**item) for item in list(payload.get("execution_cache") or []) if isinstance(item, dict)]
        self._tool_cache = {
            k: ToolAnalytic(**value) for k, value in dict(payload.get("tool_cache") or {}).items() if isinstance(value, dict)
        }
        self._user_cache = {
            k: UserAnalytic(**value) for k, value in dict(payload.get("user_cache") or {}).items() if isinstance(value, dict)
        }
        self._llm_cache = defaultdict(dict)
        for provider, entries in dict(payload.get("llm_cache") or {}).items():
            if not isinstance(entries, dict):
                continue
            self._llm_cache[provider] = {
                model: LLMMetric(**metric) for model, metric in entries.items() if isinstance(metric, dict)
            }

    def record_metric(self, name: str, value: float, *, persist: bool = True):
        """Record a metric"""
        self.metrics[name].append(value)
        self.events.append({
            "type": "metric",
            "name": name,
            "value": value,
            "timestamp": datetime.now().isoformat()
        })
        if persist:
            self._persist()

    def record_operation(self, operation: str, cost: float, duration: float, success: bool, *, persist: bool = True):
        """Record operation with cost tracking"""
        self.events.append({
            "type": "operation",
            "operation": operation,
            "cost": cost,
            "duration": duration,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })

        # Calculate ROI
        if success:
            self.roi_data[operation] = {
                "cost": cost,
                "duration": duration,
                "roi": 1.0 if cost > 0 else 0.0
            }
        if persist:
            self._persist()

    def record_execution(
        self,
        tool: str,
        intent: str,
        duration_ms: float,
        success: bool,
        complexity: float = 0.0,
        cost: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Backward-compatible execution metric entrypoint used by integration tests."""
        payload = dict(metadata or {})
        payload.update({"tool": tool, "intent": intent})
        self._execution_cache.append(
            ExecutionRecord(
                tool=str(tool),
                intent=str(intent),
                duration_ms=float(duration_ms),
                success=bool(success),
                complexity=float(complexity),
                cost=float(cost),
            )
        )
        self.record_metric(f"tool.{tool}.duration_ms", float(duration_ms), persist=False)
        self.record_metric(f"intent.{intent}.duration_ms", float(duration_ms), persist=False)
        self.events.append({
            "type": "execution",
            "tool": tool,
            "intent": intent,
            "duration": float(duration_ms),
            "success": bool(success),
            "cost": float(cost),
            "complexity": float(complexity),
            "metadata": payload,
            "timestamp": datetime.now().isoformat(),
        })
        bucket = self._tool_cache.get(tool) or ToolAnalytic(tool_name=str(tool))
        bucket.call_count += 1
        bucket.success_count += 1 if success else 0
        bucket.total_duration += float(duration_ms)
        bucket.avg_duration = bucket.total_duration / bucket.call_count if bucket.call_count else 0.0
        bucket.error_rate = 1.0 - (bucket.success_count / bucket.call_count if bucket.call_count else 0.0)
        bucket.reliability_score = bucket.success_count / bucket.call_count if bucket.call_count else 0.0
        self._tool_cache[str(tool)] = bucket
        self.record_operation(tool, float(cost), float(duration_ms), bool(success), persist=False)
        self._persist_if_needed(force=len(self._execution_cache) <= 1)

    def get_tool_analytics(self, tool_name: str) -> Optional[ToolAnalytic]:
        return self._tool_cache.get(str(tool_name))

    def record_user_interaction(
        self,
        *,
        user_id: str,
        tool_used: str,
        intent: str,
        duration_ms: float,
        language: str = "",
    ) -> None:
        user = self._user_cache.get(user_id) or UserAnalytic(user_id=str(user_id))
        user.message_count += 1
        user.total_interactions += 1
        user.avg_response_time = (
            ((user.avg_response_time * (user.total_interactions - 1)) + float(duration_ms)) / user.total_interactions
            if user.total_interactions
            else float(duration_ms)
        )
        if intent and intent not in user.top_intents:
            user.top_intents.append(str(intent))
        if language:
            user.language_preference = str(language)
        self._user_cache[str(user_id)] = user
        self.events.append({
            "type": "user_interaction",
            "user_id": user_id,
            "tool_used": tool_used,
            "intent": intent,
            "duration": float(duration_ms),
            "language": language,
            "timestamp": datetime.now().isoformat(),
        })
        self._persist_if_needed(force=user.total_interactions <= 1)

    def get_user_analytics(self, user_id: str) -> Optional[UserAnalytic]:
        return self._user_cache.get(str(user_id))

    def record_llm_call(
        self,
        provider: str,
        model: str,
        success: bool,
        latency_ms: float,
        cost_usd: float,
        tokens: int,
        quality_score: float = 0.0,
    ) -> None:
        bucket = self._llm_cache[str(provider)].get(str(model)) or LLMMetric(provider=str(provider), model=str(model))
        bucket.total_calls += 1
        bucket.success = bool(success)
        bucket.latency_ms = float(latency_ms)
        bucket.cost += float(cost_usd)
        bucket.total_tokens += int(tokens)
        bucket.quality_score = float(quality_score)
        self._llm_cache[str(provider)][str(model)] = bucket
        self.events.append({
            "type": "llm_call",
            "provider": provider,
            "model": model,
            "success": bool(success),
            "latency_ms": float(latency_ms),
            "cost": float(cost_usd),
            "tokens": int(tokens),
            "quality_score": float(quality_score),
            "timestamp": datetime.now().isoformat(),
        })
        self._persist_if_needed(force=bucket.total_calls <= 1)

    def get_llm_metrics(self, provider: str) -> Dict[str, LLMMetric]:
        return dict(self._llm_cache.get(str(provider), {}))

    def get_metrics_summary(self) -> Dict:
        """Get summary of metrics"""
        summary = {}
        for name, values in self.metrics.items():
            summary[name] = {
                "count": len(values),
                "avg": sum(values) / len(values) if values else 0,
                "min": min(values) if values else 0,
                "max": max(values) if values else 0
            }
        return summary

    def get_cost_analysis(self) -> Dict:
        """Analyze costs"""
        total_cost = sum(e["cost"] for e in self.events if e["type"] == "operation")
        operation_costs = defaultdict(float)

        for event in self.events:
            if event["type"] == "operation":
                operation_costs[event["operation"]] += event["cost"]

        return {
            "total_cost": total_cost,
            "by_operation": dict(operation_costs),
            "estimated_monthly": total_cost * 30
        }

    def get_performance_report(self) -> Dict:
        """Get performance metrics"""
        successful_ops = sum(1 for e in self.events if e.get("success"))
        total_ops = sum(1 for e in self.events if e["type"] == "operation")

        return {
            "success_rate": successful_ops / total_ops if total_ops > 0 else 0,
            "total_operations": total_ops,
            "avg_duration": sum(e["duration"] for e in self.events if "duration" in e) / total_ops if total_ops > 0 else 0
        }

    def generate_insights(self) -> Dict[str, Any]:
        """Compatibility helper for legacy dashboards/tests."""
        warnings: list[dict[str, Any]] = []
        recommendations: list[str] = []
        for tool_name, analytic in self._tool_cache.items():
            if analytic.total_calls >= 10 and analytic.reliability_score < 0.85:
                warnings.append({"type": "low_reliability", "tool": tool_name, "score": analytic.reliability_score})
                recommendations.append(f"{tool_name} için retry/healing stratejisini güçlendir")
        return {
            "summary": self.get_metrics_summary(),
            "performance": self.get_performance_report(),
            "costs": self.get_cost_analysis(),
            "warnings": warnings,
            "recommendations": recommendations,
            "event_count": len(self.events),
        }

    def get_dashboard_metrics(self) -> Dict[str, Any]:
        """Return a compact snapshot for dashboards."""
        performance = self.get_performance_report()
        costs = self.get_cost_analysis()
        return {
            "events_total": len(self.events),
            "success_rate": performance.get("success_rate", 0.0),
            "total_operations": performance.get("total_operations", 0),
            "avg_duration": performance.get("avg_duration", 0.0),
            "total_cost": costs.get("total_cost", 0.0),
            "execution_metrics": {
                "total_executions": len(self._execution_cache),
            },
            "tool_metrics": {name: value.__dict__ for name, value in self._tool_cache.items()},
            "llm_metrics": {
                provider: {model: metric.__dict__ for model, metric in entries.items()}
                for provider, entries in self._llm_cache.items()
            },
        }


# Singleton instance
_analytics_engine: Optional[AnalyticsEngine] = None


def get_analytics_engine() -> AnalyticsEngine:
    """Get or create the singleton AnalyticsEngine instance."""
    global _analytics_engine
    if _analytics_engine is None:
        _analytics_engine = AnalyticsEngine()
    return _analytics_engine
