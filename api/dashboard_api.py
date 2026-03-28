"""
Phase 5-3: Real-time Dashboard API

Provides REST endpoints for dashboard widgets with:
- Real-time metrics via WebSocket
- Historical analytics
- Performance trend tracking
- Widget-specific data endpoints
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from threading import Thread, Lock, Event
from dataclasses import dataclass, asdict
from collections import deque

from security.privacy_guard import sanitize_object

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """Single point in time metric snapshot"""
    timestamp: str
    metric_name: str
    value: float
    tags: Dict[str, str]


class MetricsStore:
    """In-memory time-series metrics storage with sliding window"""

    def __init__(self, max_history: int = 1000):
        """Initialize metrics store"""
        self.max_history = max_history
        self._metrics: Dict[str, deque] = {}
        self._lock = Lock()

    def record(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value"""
        with self._lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = deque(maxlen=self.max_history)

            snapshot = MetricSnapshot(
                timestamp=datetime.now().isoformat(),
                metric_name=metric_name,
                value=value,
                tags=tags or {}
            )
            self._metrics[metric_name].append(snapshot)

    def get_metrics(self, metric_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent metric values"""
        with self._lock:
            if metric_name not in self._metrics:
                return []

            metrics = list(self._metrics[metric_name])[-limit:]
            return [asdict(m) for m in metrics]

    def get_latest(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Get latest metric value"""
        with self._lock:
            if metric_name not in self._metrics or not self._metrics[metric_name]:
                return None

            latest = self._metrics[metric_name][-1]
            return asdict(latest)

    def get_summary(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Get metric summary (min, max, avg, count)"""
        with self._lock:
            if metric_name not in self._metrics or not self._metrics[metric_name]:
                return None

            values = [m.value for m in self._metrics[metric_name]]
            return {
                "metric_name": metric_name,
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1] if values else None
            }


class WebSocketManager:
    """Manages WebSocket connections for real-time updates"""

    def __init__(self):
        """Initialize WebSocket manager"""
        self._connections: List[Any] = []
        self._lock = Lock()
        self._subscribers: Dict[str, List[Callable]] = {}

    def register(self, connection: Any) -> None:
        """Register a new WebSocket connection"""
        with self._lock:
            self._connections.append(connection)
            logger.debug(f"WebSocket registered, total: {len(self._connections)}")

    def unregister(self, connection: Any) -> None:
        """Unregister a WebSocket connection"""
        with self._lock:
            if connection in self._connections:
                self._connections.remove(connection)
                logger.debug(f"WebSocket unregistered, total: {len(self._connections)}")

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe to a topic"""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(callback)

    def broadcast(self, topic: str, data: Dict[str, Any]) -> None:
        """Broadcast data to all subscribers"""
        with self._lock:
            callbacks = self._subscribers.get(topic, [])

        message = json.dumps({
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "data": data
        })

        for callback in callbacks:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")

    def send_all(self, message: Dict[str, Any]) -> None:
        """Send message to all connected clients"""
        data = json.dumps(message)
        with self._lock:
            for connection in self._connections:
                try:
                    connection.send(data)
                except Exception as e:
                    logger.error(f"Error sending WebSocket message: {e}")


class DashboardAPIv1:
    """Dashboard API endpoints - v1.0"""

    def __init__(self):
        """Initialize API"""
        self.metrics = MetricsStore()
        self.ws = WebSocketManager()
        self._collector_stop = Event()
        self._start_metrics_collector()

    def _start_metrics_collector(self) -> None:
        """Start background metrics collection thread"""
        def collector():
            while not self._collector_stop.is_set():
                try:
                    self._collect_metrics()
                    self._collector_stop.wait(5.0)
                except Exception as e:
                    logger.error(f"Metrics collection error: {e}")

        thread = Thread(target=collector, daemon=True, name="elyan-metrics-collector")
        thread.start()

    def _collect_metrics(self) -> None:
        """Collect current system metrics"""
        try:
            from core.performance_cache import get_all_cache_stats

            # Cache hit rate
            cache_stats = get_all_cache_stats()
            total_hits = sum(s.get("hits", 0) for s in cache_stats.values())
            total_misses = sum(s.get("misses", 0) for s in cache_stats.values())
            hit_rate = 0.0

            if total_hits + total_misses > 0:
                hit_rate = (total_hits / (total_hits + total_misses)) * 100
            self.metrics.record("cache_hit_rate", hit_rate, {"unit": "percent"})

            # Cognitive metrics
            success_rate = 0.0
            mode = "UNKNOWN"
            try:
                from core.cognitive_layer_integrator import get_cognitive_integrator
                integrator = get_cognitive_integrator()
                success_rate = float(integrator.calculate_success_rate())
                mode = str(getattr(integrator, "current_mode", "UNKNOWN") or "UNKNOWN")
            except Exception as e:
                logger.warning(f"Cognitive metrics unavailable: {e}")
            self.metrics.record("task_success_rate", success_rate, {"unit": "percent"})
            self.metrics.record("cognitive_mode", 1.0 if mode == "FOCUSED" else 0.0, {"mode": mode})
            self.metrics.record("metrics_collector_ok", 1.0, {"source": "dashboard_api"})

            # Broadcast to WebSocket subscribers
            self.ws.broadcast("metrics", {
                "cache_hit_rate": hit_rate,
                "task_success_rate": success_rate,
                "cognitive_mode": mode
            })

        except Exception as e:
            self.metrics.record("metrics_collector_ok", 0.0, {"source": "dashboard_api"})
            logger.error(f"Metric collection failed: {e}")

    def shutdown(self) -> None:
        """Stop background collector thread (tests / controlled shutdown)."""
        self._collector_stop.set()

    def get_cognitive_state(self) -> Dict[str, Any]:
        """GET /api/v1/cognitive/state"""
        try:
            from ui.widgets.cognitive_state_widget import CognitiveStateWidget

            widget = CognitiveStateWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_error_predictions(self) -> Dict[str, Any]:
        """GET /api/v1/predictions/errors"""
        try:
            from ui.widgets.cognitive_state_widget import ErrorPredictionWidget

            widget = ErrorPredictionWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_deadlock_stats(self) -> Dict[str, Any]:
        """GET /api/v1/deadlock/stats"""
        try:
            from ui.widgets.deadlock_prevention_widget import DeadlockPreventionWidget

            widget = DeadlockPreventionWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_deadlock_timeline(self, hours: int = 24) -> Dict[str, Any]:
        """GET /api/v1/deadlock/timeline?hours=24"""
        try:
            from ui.widgets.deadlock_prevention_widget import DeadlockTimeline

            data = DeadlockTimeline.get_timeline_data(hours)
            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_sleep_consolidation(self) -> Dict[str, Any]:
        """GET /api/v1/sleep/consolidation"""
        try:
            from ui.widgets.sleep_consolidation_widget import SleepConsolidationWidget

            widget = SleepConsolidationWidget()
            return {
                "success": True,
                "data": widget.render_json()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_cache_performance(self) -> Dict[str, Any]:
        """GET /api/v1/cache/performance"""
        try:
            from core.performance_cache import get_all_cache_stats

            stats = get_all_cache_stats()

            # Calculate aggregate
            total_hits = sum(s.get("hits", 0) for s in stats.values())
            total_misses = sum(s.get("misses", 0) for s in stats.values())
            total_entries = sum(s.get("entries", 0) for s in stats.values())
            hit_rate = (total_hits / (total_hits + total_misses) * 100) if (total_hits + total_misses) > 0 else 0

            return {
                "success": True,
                "aggregate": {
                    "hit_rate_pct": round(hit_rate, 1),
                    "total_hits": total_hits,
                    "total_misses": total_misses,
                    "total_entries": total_entries
                },
                "caches": stats
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_metrics_history(self, metric_name: str, limit: int = 100) -> Dict[str, Any]:
        """GET /api/v1/metrics/history?name=cache_hit_rate&limit=100"""
        try:
            data = self.metrics.get_metrics(metric_name, limit)
            return {
                "success": True,
                "metric_name": metric_name,
                "count": len(data),
                "data": data
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_metrics_summary(self, metric_name: str) -> Dict[str, Any]:
        """GET /api/v1/metrics/summary?name=cache_hit_rate"""
        try:
            summary = self.metrics.get_summary(metric_name)
            if not summary:
                return {
                    "success": False,
                    "error": f"Metric {metric_name} not found"
                }

            return {
                "success": True,
                "data": summary
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def list_available_metrics(self) -> Dict[str, Any]:
        """GET /api/v1/metrics/available"""
        try:
            with self.metrics._lock:
                metric_names = list(self.metrics._metrics.keys())

            return {
                "success": True,
                "metrics": metric_names,
                "count": len(metric_names)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    # ===== Approval System Endpoints =====

    def get_pending_approvals(self) -> Dict[str, Any]:
        """GET /api/v1/approvals/pending"""
        try:
            from core.security.approval_engine import get_approval_engine
            engine = get_approval_engine()
            pending = engine.get_pending_approvals()
            return {
                "success": True,
                "count": len(pending),
                "approvals": pending
            }
        except Exception as e:
            logger.error(f"Error getting pending approvals: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def resolve_approval(self, request_id: str, approved: bool, resolver_id: str) -> Dict[str, Any]:
        """POST /api/v1/approvals/resolve"""
        try:
            from core.security.approval_engine import get_approval_engine
            engine = get_approval_engine()
            success = engine.resolve_approval(request_id, approved, resolver_id)
            if success:
                return {
                    "success": True,
                    "message": f"Approval {'approved' if approved else 'denied'}"
                }
            else:
                return {
                    "success": False,
                    "error": "Approval request not found or already resolved"
                }
        except Exception as e:
            logger.error(f"Error resolving approval: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def bulk_resolve_approvals(self, request_ids: List[str], approved: bool, resolver_id: str) -> Dict[str, Any]:
        """POST /api/v1/approvals/bulk-resolve — Resolve multiple approvals at once"""
        try:
            from core.security.approval_engine import get_approval_engine
            engine = get_approval_engine()
            results = engine.bulk_resolve(request_ids, approved, resolver_id)
            return {
                "success": True,
                "summary": results
            }
        except Exception as e:
            logger.error(f"Error bulk resolving approvals: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_approval_workflow_metrics(self) -> Dict[str, Any]:
        """GET /api/v1/approvals/workflow-metrics — Get approval workflow metrics"""
        try:
            from core.security.approval_engine import get_approval_engine
            engine = get_approval_engine()
            metrics = engine.get_approval_metrics()
            return {
                "success": True,
                "metrics": metrics
            }
        except Exception as e:
            logger.error(f"Error getting approval metrics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ===== Run Inspector Endpoints =====

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        """GET /api/v1/runs/<run_id>"""
        try:
            try:
                from core.events.read_model import get_run_read_model
                row = get_run_read_model().get_run(run_id)
                if row:
                    return {"success": True, "run": row}
            except Exception as exc:
                logger.debug(f"Run read-model unavailable for {run_id}: {exc}")
            from core.run_store import get_run_store
            store = get_run_store()
            run = await store.get_run(run_id)
            return {"success": True, "run": run.to_dict()} if run else {"success": False, "error": "Run not found"}
        except Exception as e:
            logger.error(f"Error getting run {run_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_runs(self, limit: int = 20, status: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/v1/runs?limit=20&status=*"""
        try:
            try:
                from core.events.read_model import get_run_read_model
                runs = get_run_read_model().get_recent_runs(limit=limit, status=status)
                if runs:
                    return {"success": True, "count": len(runs), "runs": runs}
            except Exception as exc:
                logger.debug(f"Run read-model list fallback for status={status}: {exc}")
            from core.run_store import get_run_store
            store = get_run_store()
            runs = await store.list_runs(limit, status)
            return {"success": True, "count": len(runs), "runs": [r.to_dict() for r in runs]}
        except Exception as e:
            logger.error(f"Error listing runs: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def cancel_run(self, run_id: str) -> Dict[str, Any]:
        """POST /api/v1/runs/<run_id>/cancel"""
        try:
            success = False
            try:
                from core.workflow.vertical_runner import get_vertical_workflow_runner

                success = await get_vertical_workflow_runner().cancel_run(run_id)
            except Exception:
                success = False
            if not success:
                from core.run_store import get_run_store
                store = get_run_store()
                success = await store.cancel_run(run_id)
            if success:
                return {
                    "success": True,
                    "message": "Run cancelled"
                }
            else:
                return {
                    "success": False,
                    "error": "Run not found"
                }
        except Exception as e:
            logger.error(f"Error cancelling run {run_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_step_timeline(self, run_id: str) -> Dict[str, Any]:
        """GET /api/v1/runs/<run_id>/timeline — Get step timeline for Gantt visualization"""
        try:
            try:
                from core.events.event_store import get_event_store
                timeline = get_event_store().replay_to_state(run_id)
                if isinstance(timeline, dict) and timeline.get("steps"):
                    return {"success": True, "timeline": timeline}
            except Exception as exc:
                logger.debug(f"Event replay unavailable for {run_id}: {exc}")
            from core.run_store import get_run_store
            store = get_run_store()
            timeline = await store.get_step_timeline(run_id)
            return {"success": True, "timeline": timeline} if timeline else {"success": False, "error": "Run not found"}
        except Exception as e:
            logger.error(f"Error getting step timeline for {run_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ===== Memory Timeline Endpoint =====

    # ===== Analytics Endpoints =====

    async def get_approval_metrics(self, days: int = 7) -> Dict[str, Any]:
        """GET /api/v1/analytics/approvals"""
        try:
            from core.run_store import get_run_store
            import time

            store = get_run_store()
            runs = await store.list_runs(limit=1000)

            now = time.time()
            cutoff = now - (days * 86400)

            # Filter recent runs
            recent_runs = [r for r in runs if r.started_at >= cutoff]

            # Calculate metrics
            total = len(recent_runs)
            completed = len([r for r in recent_runs if r.status == "completed"])
            errors = len([r for r in recent_runs if r.status == "error"])

            success_rate = (completed / total * 100) if total > 0 else 0
            avg_duration = sum([r.duration_seconds() or 0 for r in recent_runs]) / total if total > 0 else 0

            # Top intents
            intent_counts = {}
            for run in recent_runs:
                intent = run.intent or "unknown"
                intent_counts[intent] = intent_counts.get(intent, 0) + 1

            top_intents = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            return {
                "success": True,
                "period_days": days,
                "total_runs": total,
                "completed": completed,
                "errors": errors,
                "success_rate_pct": round(success_rate, 1),
                "avg_duration_seconds": round(avg_duration, 2),
                "top_intents": [{"intent": i, "count": c} for i, c in top_intents]
            }
        except Exception as e:
            logger.error(f"Error getting approval metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_dora_metrics(self, period: int = 24) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime

            snapshot = get_elyan_runtime().metrics_collector.compute_snapshot(period_hours=float(period))
            return {
                "success": True,
                "snapshot": {
                    "period_start": snapshot.period_start,
                    "period_end": snapshot.period_end,
                    "task_completion_rate": snapshot.task_completion_rate,
                    "avg_time_to_first_result_ms": snapshot.avg_time_to_first_result_ms,
                    "task_failure_rate": snapshot.task_failure_rate,
                    "avg_recovery_time_ms": snapshot.avg_recovery_time_ms,
                    "approval_rate": snapshot.approval_rate,
                    "autonomous_decision_rate": snapshot.autonomous_decision_rate,
                    "cache_hit_rate": snapshot.cache_hit_rate,
                    "avg_tool_selection_confidence": snapshot.avg_tool_selection_confidence,
                    "performance_level": snapshot.performance_level(),
                    "improvement_suggestions": snapshot.improvement_suggestions(),
                },
            }
        except Exception as e:
            logger.error(f"Error getting DORA metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_tool_metrics(self) -> Dict[str, Any]:
        try:
            from core.events.read_model import get_run_read_model
            tools = get_run_read_model().get_tool_performance()
            tools = sorted(tools, key=lambda item: item.get("success_rate", 0.0), reverse=True)
            return {"success": True, "tools": tools}
        except Exception as e:
            logger.error(f"Error getting tool metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_health_metrics(self) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            report = get_elyan_runtime().circuit_registry.get_health_report()
            return {"success": True, "health": report}
        except Exception as e:
            logger.error(f"Error getting health metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_learning_metrics(self) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            runtime = get_elyan_runtime()
            return {
                "success": True,
                "learning": {
                    "bandit": runtime.tool_bandit.get_insights(),
                    "uncertainty": runtime.uncertainty_engine.snapshot(),
                },
            }
        except Exception as e:
            logger.error(f"Error getting learning metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_toil_metrics(self) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            report = get_elyan_runtime().capacity_planner.get_toil_report()
            return {"success": True, "toil": report}
        except Exception as e:
            logger.error(f"Error getting toil metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_multi_agent_metrics(self) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.multi_agent.handoff import get_handoff_store
            from core.semantic_memory import get_semantic_memory

            runtime = get_elyan_runtime()
            contract_net = runtime.contract_net
            world_model = runtime.world_model
            agents = []
            for agent_id, profile in contract_net.registered_agents.items():
                agents.append(
                    {
                        "agent_id": agent_id,
                        "capabilities": list(profile.capabilities),
                        "max_concurrent": profile.max_concurrent,
                        "current_load": profile.current_load,
                        "utilization": round(profile.current_load / profile.max_concurrent, 3) if profile.max_concurrent else 0.0,
                    }
                )
            agents.sort(key=lambda item: (item["current_load"], item["agent_id"]))
            facts = world_model.get_snapshot(prefix="job.")
            handoff_stats = get_handoff_store().stats()
            semantic_stats = get_semantic_memory().stats()
            gateway = getattr(runtime, "model_gateway", None)
            specialists = getattr(runtime, "specialists", None)
            security_summary = await self.get_security_summary()
            return {
                "success": True,
                "multi_agent": {
                    "registered_agents": agents,
                    "active_contracts": dict(contract_net.active_contracts),
                    "active_contract_count": len(contract_net.active_contracts),
                    "world_fact_count": len(facts),
                    "world_facts": facts,
                    "handoffs": handoff_stats,
                    "memory": {
                        "semantic": semantic_stats,
                    },
                    "model_gateway": gateway.describe() if gateway else {},
                    "security": security_summary.get("security", {}) if isinstance(security_summary, dict) else {},
                    "specialists": sorted(list(specialists.get_nextgen_team().keys())) if specialists else [],
                },
            }
        except Exception as e:
            logger.error(f"Error getting multi-agent metrics: {e}")
            return {"success": False, "error": str(e)}

    async def get_security_summary(self) -> Dict[str, Any]:
        try:
            from config.elyan_config import elyan_config
            from core.elyan_runtime import get_elyan_runtime
            from core.multi_agent.handoff import get_handoff_store
            from core.security.approval_engine import get_approval_engine
            from core.security.session_security import get_session_manager
            from core.semantic_memory import get_semantic_memory

            runtime = get_elyan_runtime()
            approval_metrics = get_approval_engine().get_workflow_metrics()
            session_stats = get_session_manager().get_session_stats()
            semantic_stats = get_semantic_memory().stats()
            handoff_stats = get_handoff_store().stats()
            return {
                "success": True,
                "security": {
                    "posture": str(elyan_config.get("operator.security_posture", "balanced") or "balanced"),
                    "deployment_scope": str(elyan_config.get("operator.deployment_scope", "single_user_local_first") or "single_user_local_first"),
                    "data_locality": str(elyan_config.get("operator.data_locality", "local_only") or "local_only"),
                    "cloud_prompt_redaction": bool(elyan_config.get("security.kvkk.redactCloudPrompts", True)),
                    "allow_cloud_fallback": bool(elyan_config.get("security.kvkk.allowCloudFallback", True)),
                    "pending_approvals": int(approval_metrics.get("pending_count", 0) or 0),
                    "active_sessions": int(session_stats.get("active_tokens", 0) or 0),
                    "session_persistence": bool(session_stats.get("persistence_enabled", False)),
                    "handoff_pending": int(handoff_stats.get("pending", 0) or 0),
                    "semantic_backend": str(semantic_stats.get("backend", "unknown") or "unknown"),
                    "model_gateway": runtime.model_gateway.describe() if getattr(runtime, "model_gateway", None) else {},
                },
            }
        except Exception as e:
            logger.error(f"Error getting security summary: {e}")
            return {"success": False, "error": str(e)}

    async def get_security_events(self, limit: int = 40) -> Dict[str, Any]:
        try:
            from core.events.event_store import EventType, get_event_store

            security_types = [
                EventType.SECURITY_DECISION_MADE,
                EventType.PROMPT_BLOCKED,
                EventType.SECRET_REDACTED,
                EventType.CLOUD_ESCALATION_DENIED,
                EventType.CLOUD_ESCALATION_APPROVED,
                EventType.SANDBOX_VIOLATION,
                EventType.TOKEN_ISSUED,
                EventType.TOKEN_REVOKED,
            ]
            store = get_event_store()
            per_type_limit = max(5, int(limit))
            collected = []
            for event_type in security_types:
                collected.extend(store.query_by_type(event_type, limit=per_type_limit))
            collected.sort(key=lambda item: float(item.timestamp or 0.0), reverse=True)
            events = []
            for event in collected[: max(1, int(limit))]:
                payload = sanitize_object(dict(event.payload or {}))
                et = str(event.event_type.value)
                level = "info"
                if "denied" in et or "blocked" in et or "violation" in et:
                    level = "error"
                elif "redacted" in et:
                    level = "warning"
                elif "issued" in et or "approved" in et:
                    level = "success"
                events.append(
                    {
                        "id": event.event_id,
                        "event_type": et,
                        "level": level,
                        "source": "security",
                        "title": et.replace("security.", "").replace("_", " "),
                        "detail": str(
                            payload.get("reason")
                            or payload.get("method")
                            or payload.get("platform")
                            or payload.get("channel_type")
                            or payload.get("aggregate_id")
                            or "security event"
                        ),
                        "timestamp": float(event.timestamp or 0.0),
                        "aggregate_id": str(event.aggregate_id or ""),
                        "payload": payload,
                    }
                )
            return {"success": True, "events": events}
        except Exception as e:
            logger.error(f"Error getting security events: {e}")
            return {"success": False, "error": str(e)}

    async def get_runtime_backends(self) -> Dict[str, Any]:
        try:
            from core.runtime_backends import get_runtime_backend_registry

            return {
                "success": True,
                "backends": get_runtime_backend_registry().describe(),
            }
        except Exception as e:
            logger.error(f"Error getting runtime backend status: {e}")
            return {"success": False, "error": str(e)}

    async def submit_feedback(self, run_id: str, satisfaction: float) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.events.event_store import EventType

            runtime = get_elyan_runtime()
            runtime.record_event(
                event_type=EventType.FEEDBACK_RECEIVED,
                aggregate_id=run_id,
                aggregate_type="run",
                payload={"satisfaction": float(satisfaction)},
            )
            return {"success": True, "run_id": run_id, "satisfaction": float(satisfaction)}
        except Exception as e:
            logger.error(f"Error recording feedback: {e}")
            return {"success": False, "error": str(e)}

    async def add_htn_method(self, task_name: str, subtasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.planning.htn_planner import Task

            runtime = get_elyan_runtime()
            plan = [
                Task(
                    name=str(item.get("name") or item.get("action") or ""),
                    parameters=dict(item.get("parameters") or {}),
                    preconditions=list(item.get("preconditions") or []),
                    is_primitive=bool(item.get("is_primitive", True)),
                )
                for item in subtasks
                if isinstance(item, dict)
            ]
            runtime.htn_planner.record_successful_plan(task_name, plan)
            return {"success": True, "task_name": task_name, "subtask_count": len(plan)}
        except Exception as e:
            logger.error(f"Error adding HTN method: {e}")
            return {"success": False, "error": str(e)}

    async def get_approval_trends(self, days: int = 7) -> Dict[str, Any]:
        """GET /api/v1/analytics/approval-trends"""
        try:
            from core.run_store import get_run_store
            from datetime import datetime, timedelta
            import time

            store = get_run_store()
            runs = await store.list_runs(limit=1000)

            # Group by day
            daily_stats = {}
            for run in runs:
                ts = datetime.fromtimestamp(run.started_at)
                day = ts.strftime("%Y-%m-%d")

                if day not in daily_stats:
                    daily_stats[day] = {"total": 0, "completed": 0, "errors": 0}

                daily_stats[day]["total"] += 1
                if run.status == "completed":
                    daily_stats[day]["completed"] += 1
                elif run.status == "error":
                    daily_stats[day]["errors"] += 1

            # Calculate rates
            trend_data = []
            for day in sorted(daily_stats.keys())[-days:]:
                stats = daily_stats[day]
                rate = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
                trend_data.append({
                    "date": day,
                    "runs": stats["total"],
                    "success_rate": round(rate, 1),
                    "errors": stats["errors"]
                })

            return {
                "success": True,
                "period_days": days,
                "trend": trend_data
            }
        except Exception as e:
            logger.error(f"Error getting approval trends: {e}")
            return {"success": False, "error": str(e)}

    async def get_memory_timeline(self, limit: int = 20) -> Dict[str, Any]:
        """GET /api/v1/memory/timeline?limit=20"""
        try:
            from core.run_store import get_run_store
            import os
            from pathlib import Path

            store = get_run_store()
            events = []

            # Get recent runs
            runs = await store.list_runs(limit)
            for run in runs:
                events.append({
                    "type": "run_completed",
                    "timestamp": run.completed_at or run.started_at,
                    "summary": f"{run.intent} ({run.status})",
                    "run_id": run.run_id
                })

            # Get daily summaries from memory
            memory_path = Path(os.path.expanduser("~/.elyan/memory/daily"))
            if memory_path.exists():
                for file_path in sorted(memory_path.glob("*.md"), reverse=True)[:7]:
                    try:
                        with open(file_path, "r") as f:
                            content = f.read()
                            # Extract first line as summary
                            first_line = content.split("\n")[0]
                            events.append({
                                "type": "daily_summary",
                                "timestamp": file_path.stat().st_mtime,
                                "summary": first_line.replace("#", "").strip()[:100],
                                "file": file_path.name
                            })
                    except Exception as exc:
                        logger.debug(f"Skipping memory summary {file_path}: {exc}")

            # Sort by timestamp descending
            events.sort(key=lambda e: e["timestamp"], reverse=True)
            events = events[:limit]

            return {
                "success": True,
                "count": len(events),
                "events": events
            }
        except Exception as e:
            logger.error(f"Error getting memory timeline: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_smart_suggestions(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET /api/v1/suggestions/smart?context={json}

        Provides intelligent suggestions based on user behavior patterns,
        time of day, and previous actions using the adaptive engine.
        """
        try:
            from core.adaptive_engine import get_adaptive_engine

            engine = get_adaptive_engine()
            if context is None:
                context = {}

            # Add current time and session context
            context.setdefault("time_of_day", self._get_time_of_day())
            context.setdefault("timestamp", datetime.now().isoformat())

            suggestions = engine.get_smart_suggestions(context)

            return {
                "success": True,
                "count": len(suggestions),
                "suggestions": suggestions
            }
        except Exception as e:
            logger.error(f"Error getting smart suggestions: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_adaptive_response(
        self,
        intent: str,
        available_actions: List[str],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """POST /api/v1/suggestions/adaptive

        Recommends best action for a given intent based on adaptive learning.
        Returns recommended action with confidence score and alternatives.
        """
        try:
            from core.adaptive_engine import get_adaptive_engine

            engine = get_adaptive_engine()
            if context is None:
                context = {}

            response = engine.get_adaptive_response(intent, context, available_actions)
            return response
        except Exception as e:
            logger.error(f"Error getting adaptive response: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def learn_interaction(
        self,
        intent: str,
        action: str,
        success: bool,
        context: Optional[Dict[str, Any]] = None,
        duration: float = 0.0
    ) -> Dict[str, Any]:
        """POST /api/v1/learning/record

        Records user interaction for the adaptive engine to learn from.
        Updates pattern data for future suggestions.
        """
        try:
            from core.adaptive_engine import get_adaptive_engine

            engine = get_adaptive_engine()
            if context is None:
                context = {}

            engine.learn_from_interaction(intent, action, success, context, duration)

            return {
                "success": True,
                "message": f"Learned: {intent} -> {action} ({'success' if success else 'failed'})"
            }
        except Exception as e:
            logger.error(f"Error recording learning: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def _get_time_of_day() -> str:
        """Get current time of day category."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"


# Global API instance
_dashboard_api: Optional[DashboardAPIv1] = None


def get_dashboard_api() -> DashboardAPIv1:
    """Get or create global dashboard API instance"""
    global _dashboard_api
    if _dashboard_api is None:
        _dashboard_api = DashboardAPIv1()
    return _dashboard_api


def reset_dashboard_api() -> None:
    """Reset API instance (for testing)"""
    global _dashboard_api
    if _dashboard_api is not None:
        try:
            _dashboard_api.shutdown()
        except Exception as exc:
            logger.debug(f"Dashboard API shutdown skipped: {exc}")
    _dashboard_api = None
