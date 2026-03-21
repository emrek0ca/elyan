from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from config.elyan_config import elyan_config
from core.automation_registry import automation_registry
from core.briefing_manager import get_briefing_manager
from core.device_sync import get_device_sync_store
from core.learning_control import get_learning_control_plane
from core.predictive_maintenance import PredictionSeverity, get_predictive_maintenance
from core.proactive.maintenance import maintenance
from core.proactive.intervention import get_intervention_manager
from core.self_improvement import get_self_improvement
from core.storage_paths import resolve_elyan_data_dir
from core.task_brain import task_brain
from core.advanced_features import get_suggestion_engine
from utils.logger import get_logger

logger = get_logger("autopilot")


def _now() -> float:
    return time.time()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


@dataclass
class AutopilotAction:
    kind: str
    title: str
    status: str
    success: bool
    source: str
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata or {})
        return payload


class AutopilotEngine:
    DEFAULT_CONFIG: dict[str, Any] = {
        "enabled": True,
        "tick_interval_seconds": 120,
        "maintenance_interval_seconds": 6 * 3600,
        "briefing_interval_seconds": 24 * 3600,
        "suggestion_interval_seconds": 30 * 60,
        "task_review_interval_seconds": 15 * 60,
        "intervention_interval_seconds": 5 * 60,
        "automation_health_interval_seconds": 10 * 60,
        "reconcile_interval_seconds": 24 * 3600,
        "max_recent_users": 5,
        "max_user_suggestions": 3,
        "max_actions_per_tick": 10,
        "stale_task_minutes": 30,
        "stale_intervention_minutes": 5,
        "predictive_monitoring_enabled": True,
    }

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        maintenance_engine: Any | None = None,
        briefing_manager: Any | None = None,
        suggestion_engine: Any | None = None,
        predictive_maintenance: Any | None = None,
        intervention_manager: Any | None = None,
        device_sync_store: Any | None = None,
        learning_control: Any | None = None,
        task_brain_store: Any | None = None,
        automation_registry_store: Any | None = None,
        notify_callback: Callable[[str, dict[str, Any]], Awaitable[Any] | Any] | None = None,
    ) -> None:
        runtime_cfg = dict(elyan_config.get("autopilot", {}) or {})
        self.config = _deep_merge(self.DEFAULT_CONFIG, dict(config or runtime_cfg))
        self.enabled = bool(self.config.get("enabled", True))
        self.maintenance_engine = maintenance_engine or maintenance
        self.briefing_manager = briefing_manager or get_briefing_manager()
        self.suggestion_engine = suggestion_engine or get_suggestion_engine()
        self.predictive_maintenance = predictive_maintenance or get_predictive_maintenance()
        self.intervention_manager = intervention_manager or get_intervention_manager()
        self.device_sync_store = device_sync_store or get_device_sync_store()
        self.learning_control = learning_control or get_learning_control_plane()
        self.task_brain = task_brain_store or task_brain
        self.automation_registry = automation_registry_store or automation_registry
        self.self_improvement = get_self_improvement()
        self.notify_callback = notify_callback
        self.state_path = resolve_elyan_data_dir() / "autopilot" / "autopilot_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._running = False
        self._task: asyncio.Task | None = None
        self._prediction_task: asyncio.Task | None = None
        self._agent: Any | None = None
        self._last_actions: list[dict[str, Any]] = list(self._state.get("last_actions") or [])
        self._last_briefing: dict[str, Any] = dict(self._state.get("last_briefing") or {})
        self._last_suggestions: list[dict[str, Any]] = list(self._state.get("last_suggestions") or [])
        self._last_task_review: list[dict[str, Any]] = list(self._state.get("last_task_review") or [])
        self._last_interventions: list[dict[str, Any]] = list(self._state.get("last_interventions") or [])
        self._last_automation_health: dict[str, Any] = dict(self._state.get("last_automation_health") or {})
        self._started_at = float(self._state.get("started_at") or 0.0)
        self._last_tick_at = float(self._state.get("last_tick_at") or 0.0)
        self._last_tick_reason = str(self._state.get("last_tick_reason") or "")
        self._tick_count = int(self._state.get("tick_count") or 0)
        self._last_maintenance_at = float(self._state.get("last_maintenance_at") or 0.0)
        self._last_briefing_at = float(self._state.get("last_briefing_at") or 0.0)
        self._last_suggestion_at = float(self._state.get("last_suggestion_at") or 0.0)
        self._last_task_review_at = float(self._state.get("last_task_review_at") or 0.0)
        self._last_intervention_at = float(self._state.get("last_intervention_at") or 0.0)
        self._last_automation_health_at = float(self._state.get("last_automation_health_at") or 0.0)
        self._last_reconcile_at = float(self._state.get("last_reconcile_at") or 0.0)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _persist_state(self) -> None:
        payload = {
            "enabled": self.enabled,
            "running": self._running,
            "started_at": self._started_at,
            "last_tick_at": self._last_tick_at,
            "last_tick_reason": self._last_tick_reason,
            "tick_count": self._tick_count,
            "last_maintenance_at": self._last_maintenance_at,
            "last_briefing_at": self._last_briefing_at,
            "last_suggestion_at": self._last_suggestion_at,
            "last_task_review_at": self._last_task_review_at,
            "last_intervention_at": self._last_intervention_at,
            "last_automation_health_at": self._last_automation_health_at,
            "last_reconcile_at": self._last_reconcile_at,
            "last_actions": self._last_actions[-10:],
            "last_briefing": self._last_briefing,
            "last_suggestions": self._last_suggestions[-15:],
            "last_task_review": self._last_task_review[-15:],
            "last_interventions": self._last_interventions[-15:],
            "last_automation_health": self._last_automation_health,
            "config": dict(self.config),
        }
        try:
            self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"Autopilot state persist failed: {exc}")

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if not callable(self.notify_callback):
            return
        try:
            result = self.notify_callback(event_type, data)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.debug(f"Autopilot notify failed: {exc}")

    @staticmethod
    def _due(last_at: float, interval_seconds: int) -> bool:
        if interval_seconds <= 0:
            return False
        if last_at <= 0:
            return True
        return (_now() - float(last_at)) >= float(interval_seconds)

    @staticmethod
    def _safe_text(value: Any, limit: int = 160) -> str:
        text = " ".join(str(value or "").strip().split())
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    async def start(
        self,
        agent: Any | None = None,
        notify_callback: Callable[[str, dict[str, Any]], Awaitable[Any] | Any] | None = None,
    ) -> dict[str, Any]:
        self._agent = agent or self._agent
        if notify_callback is not None:
            self.notify_callback = notify_callback
        if self._running:
            return self.status()
        if not self.enabled:
            self._persist_state()
            return self.status()
        self._running = True
        self._started_at = self._started_at or _now()
        if bool(self.config.get("predictive_monitoring_enabled", True)) and not getattr(self.predictive_maintenance, "monitoring_active", False):
            try:
                self._prediction_task = asyncio.create_task(self.predictive_maintenance.start_monitoring())
            except Exception as exc:
                logger.debug(f"Predictive monitoring start skipped: {exc}")
        self._task = asyncio.create_task(self._loop())
        asyncio.create_task(self.run_tick(reason="startup"))
        self._persist_state()
        logger.info("Autopilot engine started")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._prediction_task:
            try:
                self.predictive_maintenance.stop_monitoring()
            except Exception:
                pass
            self._prediction_task.cancel()
            self._prediction_task = None
        self._persist_state()
        logger.info("Autopilot engine stopped")
        return self.status()

    async def _loop(self) -> None:
        interval = max(15, int(self.config.get("tick_interval_seconds", 120) or 120))
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self.run_tick(reason="scheduled")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Autopilot loop error: {exc}")
                await asyncio.sleep(min(60, interval))

    async def run_tick(
        self,
        *,
        agent: Any | None = None,
        reason: str = "scheduled",
        force: bool | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return self.status()

        agent = agent or self._agent
        force_cycles = bool(force) if force is not None else str(reason or "").strip().lower() != "scheduled"
        started_at = _now()
        self._tick_count += 1
        self._last_tick_at = started_at
        self._last_tick_reason = str(reason or "scheduled")

        actions: list[AutopilotAction] = []
        summary: dict[str, Any] = {
            "reason": self._last_tick_reason,
            "tick_count": self._tick_count,
        }

        try:
            if force_cycles or self._due(self._last_maintenance_at, int(self.config.get("maintenance_interval_seconds", 21600) or 21600)):
                maintenance_result = await self._run_maintenance_cycle()
                if maintenance_result:
                    actions.append(maintenance_result)
                    self._last_maintenance_at = started_at

            if force_cycles or self._due(self._last_briefing_at, int(self.config.get("briefing_interval_seconds", 86400) or 86400)):
                briefing_result = await self._run_briefing_cycle()
                if briefing_result:
                    actions.append(briefing_result)
                    self._last_briefing_at = started_at

            if force_cycles or self._due(self._last_suggestion_at, int(self.config.get("suggestion_interval_seconds", 1800) or 1800)):
                suggestion_result = await self._run_suggestion_cycle()
                if suggestion_result:
                    actions.append(suggestion_result)
                    self._last_suggestion_at = started_at

            if force_cycles or self._due(self._last_task_review_at, int(self.config.get("task_review_interval_seconds", 900) or 900)):
                review_result = await self._run_task_review_cycle()
                if review_result:
                    actions.append(review_result)
                    self._last_task_review_at = started_at

            if force_cycles or self._due(self._last_intervention_at, int(self.config.get("intervention_interval_seconds", 300) or 300)):
                intervention_result = await self._run_intervention_cycle()
                if intervention_result:
                    actions.append(intervention_result)
                    self._last_intervention_at = started_at

            if force_cycles or self._due(self._last_automation_health_at, int(self.config.get("automation_health_interval_seconds", 600) or 600)):
                automation_result = await self._run_automation_health_cycle()
                if automation_result:
                    actions.append(automation_result)
                    self._last_automation_health_at = started_at

            if force_cycles or self._due(self._last_reconcile_at, int(self.config.get("reconcile_interval_seconds", 86400) or 86400)):
                reconcile_result = await self._run_reconcile_cycle()
                if reconcile_result:
                    actions.append(reconcile_result)
                    self._last_reconcile_at = started_at

            summary["actions"] = [action.to_dict() for action in actions[: int(self.config.get("max_actions_per_tick", 10) or 10)]]
            summary["success_count"] = sum(1 for action in actions if action.success)
            summary["action_count"] = len(actions)
            summary["duration_ms"] = int((_now() - started_at) * 1000)

            self._last_actions = summary["actions"][-10:]
            self._persist_state()
            await self._emit("autopilot", summary)
            return self.status()
        except Exception as exc:
            logger.error(f"Autopilot tick failed: {exc}")
            summary["error"] = str(exc)
            summary["duration_ms"] = int((_now() - started_at) * 1000)
            self._last_actions = [AutopilotAction(
                kind="tick_error",
                title="Autopilot tick failed",
                status="error",
                success=False,
                source="autopilot",
                summary=str(exc),
            ).to_dict()]
            self._persist_state()
            await self._emit("autopilot", summary)
            return self.status()

    async def _run_maintenance_cycle(self) -> AutopilotAction | None:
        try:
            maintenance_result = await self.maintenance_engine.run_full_maintenance()
            safe_actions = {"clear_cache", "cleanup_temp", "optimize_processes"}
            preventive_actions: list[str] = []
            for prediction in list(getattr(self.predictive_maintenance, "predictions", []) or []):
                action = str(getattr(prediction, "prevention_action", "") or "").strip()
                severity = getattr(prediction, "severity", None)
                if action in safe_actions and severity in {PredictionSeverity.CRITICAL, PredictionSeverity.WARNING}:
                    try:
                        await self.predictive_maintenance.trigger_preventive_action(action)
                        preventive_actions.append(action)
                    except Exception as exc:
                        logger.debug(f"Preventive action skipped: {exc}")

            action = AutopilotAction(
                kind="maintenance",
                title="System maintenance",
                status="completed" if bool(maintenance_result.get("success", True)) else "failed",
                success=bool(maintenance_result.get("success", True)),
                source="maintenance",
                summary=f"freed={maintenance_result.get('total_freed_mb', 0)}MB",
                metadata={
                    "result": maintenance_result,
                    "preventive_actions": preventive_actions,
                    "predictive": self.predictive_maintenance.get_summary(),
                },
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-maintenance-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_maintenance",
                score=1.0 if action.success else 0.0,
                metadata=action.metadata,
            )
            await self._emit("autopilot_action", action.to_dict())
            return action
        except Exception as exc:
            logger.debug(f"Autopilot maintenance cycle failed: {exc}")
            return AutopilotAction(
                kind="maintenance",
                title="System maintenance",
                status="failed",
                success=False,
                source="maintenance",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _run_briefing_cycle(self) -> AutopilotAction | None:
        try:
            briefing = await self.briefing_manager.get_proactive_briefing()
            if not briefing.get("success"):
                return AutopilotAction(
                    kind="briefing",
                    title="Daily briefing",
                    status="failed",
                    success=False,
                    source="briefing_manager",
                    summary=str(briefing.get("error") or "briefing_failed"),
                    metadata=dict(briefing),
                )
            text = str(briefing.get("briefing") or "").strip()
            action = AutopilotAction(
                kind="briefing",
                title="Daily briefing",
                status="completed",
                success=True,
                source="briefing_manager",
                summary=self._safe_text(text, 140),
                metadata=dict(briefing),
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-briefing-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_briefing",
                score=1.0,
                metadata=action.metadata,
            )
            self._last_briefing = dict(briefing)
            await self._emit("briefing", {"briefing": text, "metrics": briefing.get("metrics", {}), "timestamp": briefing.get("timestamp")})
            return action
        except Exception as exc:
            logger.debug(f"Autopilot briefing cycle failed: {exc}")
            return AutopilotAction(
                kind="briefing",
                title="Daily briefing",
                status="failed",
                success=False,
                source="briefing_manager",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _recent_user_ids(self) -> list[str]:
        users: list[str] = []
        try:
            if hasattr(self.device_sync_store, "list_recent_users"):
                rows = self.device_sync_store.list_recent_users(limit=int(self.config.get("max_recent_users", 5) or 5))
                for row in list(rows or []):
                    uid = str((row or {}).get("user_id") or "").strip()
                    if uid and uid not in users:
                        users.append(uid)
        except Exception as exc:
            logger.debug(f"Recent user lookup failed: {exc}")
        if not users:
            try:
                tasks = self.task_brain.list_all(limit=int(self.config.get("max_recent_users", 5) or 5))
                for task in tasks:
                    uid = str(getattr(task, "context", {}).get("user_id") or "").strip()
                    if uid and uid not in users:
                        users.append(uid)
            except Exception:
                pass
        return users

    async def _run_suggestion_cycle(self) -> AutopilotAction | None:
        try:
            suggestions: list[dict[str, Any]] = []
            digest_rows: list[dict[str, Any]] = []
            for uid in await self._recent_user_ids():
                try:
                    snapshot = self.device_sync_store.get_user_snapshot(uid, limit=10)
                    recent_requests = [
                        str(item.get("request_text") or "").strip()
                        for item in list(snapshot.get("requests") or [])
                        if str(item.get("request_text") or "").strip()
                    ]
                    recent_tasks = [
                        str(getattr(task, "objective", "") or "").strip()
                        for task in self.task_brain.list_for_user(uid, limit=5)
                        if str(getattr(task, "objective", "") or "").strip()
                    ]
                    recent_commands = recent_requests + recent_tasks
                    if not recent_commands:
                        continue
                    runtime_context = await self.learning_control.get_runtime_context(
                        uid,
                        {
                            "request": recent_commands[-1],
                            "channel": "autopilot",
                            "provider": "ollama",
                            "model": "",
                            "base_model_id": "",
                            "metadata": {"source": "autopilot", "task_count": len(recent_tasks), "request_count": len(recent_requests)},
                        },
                    )
                    user_preferences = dict(runtime_context.get("runtime_profile") or {})
                    rows = self.suggestion_engine.analyze_user_behavior(recent_commands, user_preferences)
                    for row in rows[: int(self.config.get("max_user_suggestions", 3) or 3)]:
                        suggestions.append(
                            {
                                "user_id": uid,
                                "task": row.task,
                                "description": row.description,
                                "priority": row.priority,
                                "reason": row.reason,
                                "confidence": float(row.confidence or 0.0),
                            }
                        )
                        self.learning_control.record_feedback(
                            user_id=uid,
                            interaction_id=f"autopilot-suggestion-{uuid.uuid4().hex[:8]}",
                            event_type="autopilot_suggestion",
                            score=float(row.confidence or 0.0),
                            metadata={
                                "task": row.task,
                                "description": row.description,
                                "reason": row.reason,
                                "priority": row.priority,
                            },
                    )
                except Exception as exc:
                    logger.debug(f"Autopilot suggestion scan failed for {uid}: {exc}")
                    continue

            if not suggestions:
                for uid in await self._recent_user_ids():
                    try:
                        digest = {}
                        if hasattr(self.learning_control, "build_learning_digest"):
                            digest = self.learning_control.build_learning_digest(
                                uid,
                                request_meta={"source": "autopilot"},
                                limit=8,
                            )
                        if isinstance(digest, dict) and digest:
                            digest_rows.append(
                                {
                                    "user_id": uid,
                                    "digest": digest,
                                }
                            )
                            for item in list(digest.get("next_actions") or [])[: int(self.config.get("max_user_suggestions", 3) or 3)]:
                                if not isinstance(item, dict):
                                    continue
                                suggestions.append(
                                    {
                                        "user_id": uid,
                                        "task": str(item.get("title") or item.get("reason") or "learning_next_action"),
                                        "description": str(item.get("description") or ""),
                                        "priority": str(item.get("priority") or "medium"),
                                        "reason": str(item.get("reason") or "learning_digest"),
                                        "confidence": float(digest.get("learning_score", 0.0) or 0.0),
                                    }
                                )
                        if suggestions:
                            break
                    except Exception as exc:
                        logger.debug(f"Autopilot learning digest suggestion scan failed for {uid}: {exc}")

            if not suggestions:
                return None

            action = AutopilotAction(
                kind="suggestion_scan",
                title="Proactive suggestions",
                status="completed",
                success=True,
                source="suggestion_engine",
                summary=f"{len(suggestions)} suggestions",
                metadata={"suggestions": suggestions[:15], "learning_digests": digest_rows[:5]},
            )
            self._last_suggestions = suggestions[:15]
            await self._emit("suggestion", {"items": self._last_suggestions})
            return action
        except Exception as exc:
            logger.debug(f"Autopilot suggestion cycle failed: {exc}")
            return AutopilotAction(
                kind="suggestion_scan",
                title="Proactive suggestions",
                status="failed",
                success=False,
                source="suggestion_engine",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _run_task_review_cycle(self) -> AutopilotAction | None:
        try:
            stale_minutes = int(self.config.get("stale_task_minutes", 30) or 30)
            cutoff = _now() - (stale_minutes * 60)
            stale_rows: list[dict[str, Any]] = []
            for record in self.task_brain.list_all(limit=100, states=["pending", "planning", "executing", "verifying"]):
                updated_at = float(getattr(record, "updated_at", 0.0) or 0.0)
                if updated_at and updated_at < cutoff:
                    stale_rows.append(
                        {
                            "task_id": str(getattr(record, "task_id", "") or ""),
                            "state": str(getattr(record, "state", "") or ""),
                            "objective": self._safe_text(getattr(record, "objective", "") or "", 140),
                            "age_minutes": int(((_now() - updated_at) / 60.0)),
                            "action": "resume" if str(getattr(record, "state", "") or "").strip().lower() in {"executing", "verifying"} else "clarify",
                        }
                    )
            if not stale_rows:
                return None
            self._last_task_review = stale_rows[:15]
            action = AutopilotAction(
                kind="task_review",
                title="Stale task review",
                status="completed",
                success=True,
                source="task_brain",
                summary=f"{len(stale_rows)} stale tasks",
                metadata={"tasks": stale_rows[:15]},
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-task-review-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_task_review",
                score=1.0,
                metadata=action.metadata,
            )
            await self._emit("task_review", {"tasks": stale_rows[:15]})
            return action
        except Exception as exc:
            logger.debug(f"Autopilot task review failed: {exc}")
            return AutopilotAction(
                kind="task_review",
                title="Stale task review",
                status="failed",
                success=False,
                source="task_brain",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _run_intervention_cycle(self) -> AutopilotAction | None:
        try:
            pending = self.intervention_manager.list_pending()
            if not pending:
                return None
            stale_minutes = int(self.config.get("stale_intervention_minutes", 5) or 5)
            now = _now()
            reminders: list[dict[str, Any]] = []
            for item in pending:
                created_at = float(item.get("ts") or 0.0)
                if created_at and (now - created_at) < stale_minutes * 60:
                    continue
                reminders.append(
                    {
                        "id": str(item.get("id") or ""),
                        "prompt": self._safe_text(item.get("prompt") or "", 160),
                        "options": list(item.get("options") or []),
                        "age_minutes": int((now - created_at) / 60.0) if created_at else 0,
                    }
                )
            if not reminders:
                return None
            self._last_interventions = reminders[:15]
            action = AutopilotAction(
                kind="intervention",
                title="Pending approvals",
                status="completed",
                success=True,
                source="intervention_manager",
                summary=f"{len(reminders)} reminder(s)",
                metadata={"reminders": reminders[:15]},
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-intervention-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_intervention",
                score=1.0,
                metadata=action.metadata,
            )
            await self._emit("intervention", {"reminders": reminders[:15]})
            return action
        except Exception as exc:
            logger.debug(f"Autopilot intervention cycle failed: {exc}")
            return AutopilotAction(
                kind="intervention",
                title="Pending approvals",
                status="failed",
                success=False,
                source="intervention_manager",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _run_automation_health_cycle(self) -> AutopilotAction | None:
        try:
            health = self.automation_registry.get_module_health(limit=12)
            self._last_automation_health = dict(health)
            summary = dict(health.get("summary") or {})
            action = AutopilotAction(
                kind="automation_health",
                title="Automation health",
                status="completed",
                success=True,
                source="automation_registry",
                summary=f"healthy={summary.get('healthy', 0)} failing={summary.get('failing', 0)}",
                metadata={"health": health},
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-automation-health-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_automation_health",
                score=float(summary.get("healthy", 0) or 0),
                metadata=action.metadata,
            )
            await self._emit("automation_health", health)
            return action
        except Exception as exc:
            logger.debug(f"Autopilot automation-health cycle failed: {exc}")
            return AutopilotAction(
                kind="automation_health",
                title="Automation health",
                status="failed",
                success=False,
                source="automation_registry",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    async def _run_reconcile_cycle(self) -> AutopilotAction | None:
        try:
            result = self.automation_registry.reconcile_module_tasks()
            action = AutopilotAction(
                kind="reconcile",
                title="Automation reconciliation",
                status="completed",
                success=True,
                source="automation_registry",
                summary=f"removed={result.get('removed_count', 0)}",
                metadata={"result": result},
            )
            self.learning_control.record_feedback(
                user_id="system",
                interaction_id=f"autopilot-reconcile-{uuid.uuid4().hex[:8]}",
                event_type="autopilot_reconcile",
                score=1.0,
                metadata=action.metadata,
            )
            await self._emit("reconcile", result)
            return action
        except Exception as exc:
            logger.debug(f"Autopilot reconcile cycle failed: {exc}")
            return AutopilotAction(
                kind="reconcile",
                title="Automation reconciliation",
                status="failed",
                success=False,
                source="automation_registry",
                summary=str(exc),
                metadata={"error": str(exc)},
            )

    def status(self) -> dict[str, Any]:
        maintenance_summary = {}
        try:
            if hasattr(self.maintenance_engine, "get_summary") and callable(getattr(self.maintenance_engine, "get_summary")):
                maintenance_summary = self.maintenance_engine.get_summary()
            else:
                maintenance_summary = maintenance.get_summary()
        except Exception as exc:
            maintenance_summary = {"status": "error", "error": str(exc)}

        predictive_summary = {}
        try:
            predictive_summary = self.predictive_maintenance.get_summary()
        except Exception as exc:
            predictive_summary = {"status": "error", "error": str(exc)}

        automation_summary = {}
        try:
            automation_summary = self.automation_registry.get_module_health(limit=5)
        except Exception as exc:
            automation_summary = {"status": "error", "error": str(exc)}

        return {
            "enabled": self.enabled,
            "running": self._running,
            "started_at": self._started_at,
            "last_tick_at": self._last_tick_at,
            "last_tick_reason": self._last_tick_reason,
            "tick_count": self._tick_count,
            "last_actions": list(self._last_actions[-10:]),
            "last_briefing": dict(self._last_briefing),
            "last_suggestions": list(self._last_suggestions[-15:]),
            "last_task_review": list(self._last_task_review[-15:]),
            "last_interventions": list(self._last_interventions[-15:]),
            "last_automation_health": dict(self._last_automation_health),
            "maintenance": maintenance_summary,
            "predictive": predictive_summary,
            "automation": automation_summary,
            "state_path": str(self.state_path),
            "config": {
                "tick_interval_seconds": int(self.config.get("tick_interval_seconds", 120) or 120),
                "maintenance_interval_seconds": int(self.config.get("maintenance_interval_seconds", 21600) or 21600),
                "briefing_interval_seconds": int(self.config.get("briefing_interval_seconds", 86400) or 86400),
                "suggestion_interval_seconds": int(self.config.get("suggestion_interval_seconds", 1800) or 1800),
                "task_review_interval_seconds": int(self.config.get("task_review_interval_seconds", 900) or 900),
                "intervention_interval_seconds": int(self.config.get("intervention_interval_seconds", 300) or 300),
                "predictive_monitoring_enabled": bool(self.config.get("predictive_monitoring_enabled", True)),
            },
        }

    def get_status(self) -> dict[str, Any]:
        return self.status()

    def snapshot(self) -> dict[str, Any]:
        return self.status()


_autopilot: AutopilotEngine | None = None


def get_autopilot() -> AutopilotEngine:
    global _autopilot
    if _autopilot is None:
        _autopilot = AutopilotEngine()
    return _autopilot


__all__ = ["AutopilotAction", "AutopilotEngine", "get_autopilot"]
