from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


class FakeMaintenance:
    def __init__(self):
        self.calls = 0
        self.preventive_actions: list[str] = []

    async def run_full_maintenance(self):
        self.calls += 1
        return {"success": True, "tasks_completed": 1, "total_freed_mb": 2.5}

    def get_summary(self):
        return {"monitoring_active": False, "metrics_collected": 10, "active_predictions": 1}


class FakeBriefingManager:
    async def get_proactive_briefing(self, include_weather=True, include_calendar=True, include_news=True):
        return {
            "success": True,
            "briefing": "Günün özeti hazır.",
            "metrics": {"health_score": 92, "cpu": 12.5, "mem": 18.2},
            "timestamp": "2026-03-21T13:30:00",
        }


class FakeSuggestionEngine:
    def analyze_user_behavior(self, recent_commands, user_preferences):
        return [
            SimpleNamespace(
                task="organize_files",
                description="Dosyaları düzenle",
                priority="medium",
                reason="pattern detected",
                confidence=0.8,
            )
        ]


class FakePredictiveMaintenance:
    def __init__(self):
        self.monitoring_active = False
        self.started = 0
        self.stopped = 0
        self.last_action = ""
        self.predictions = [
            SimpleNamespace(
                severity=SimpleNamespace(value="critical"),  # ignored by membership check
                prevention_action="clear_cache",
            )
        ]

    async def start_monitoring(self):
        self.started += 1
        self.monitoring_active = True

    def stop_monitoring(self):
        self.stopped += 1
        self.monitoring_active = False

    async def trigger_preventive_action(self, action: str):
        self.last_action = action

    def get_summary(self):
        return {
            "monitoring_active": self.monitoring_active,
            "metrics_collected": 3,
            "active_predictions": len(self.predictions),
            "critical_predictions": 1,
            "warning_predictions": 0,
            "data_points": 3,
        }


class FakeInterventionManager:
    def list_pending(self):
        return [
            {
                "id": "req-1",
                "prompt": "Google hesabını bağla",
                "options": ["Onayla", "İptal Et"],
                "ts": 0.0,
            }
        ]


class FakeDeviceSyncStore:
    def list_recent_users(self, *, limit: int = 10):
        return [{"user_id": "42", "updated_at": 10.0, "session_count": 1}]

    def get_user_snapshot(self, user_id: str, *, limit: int = 20):
        return {
            "user_id": user_id,
            "devices": [],
            "requests": [
                {"request_text": "dosyaları düzenle ve notları yedekle"},
                {"request_text": "notlarını organize et"},
            ],
        }


class FakeTask:
    def __init__(self, task_id: str, objective: str, state: str, updated_at: float):
        self.task_id = task_id
        self.objective = objective
        self.state = state
        self.updated_at = updated_at
        self.context = {"user_id": "42"}


class FakeTaskBrain:
    def list_all(self, *, limit: int = 100, states: list[str] | None = None):
        return [
            FakeTask("t1", "Dosyaları organize et", "pending", 0.0),
            FakeTask("t2", "Toplantı planla", "executing", 0.0),
        ]

    def list_for_user(self, user_id: str, *, limit: int = 10, states: list[str] | None = None):
        return [FakeTask("t3", "Araştırmayı özetle", "pending", 0.0)]


class FakeLearningControl:
    def __init__(self):
        self.feedback_events: list[dict[str, object]] = []

    async def get_runtime_context(self, user_id: str, request_meta: dict | None = None):
        return {"runtime_profile": {"preferred_language": "tr", "response_length_bias": "short"}}

    def record_feedback(self, **kwargs):
        self.feedback_events.append(dict(kwargs))
        return {"ok": True, **kwargs}


class FakeAutomationRegistry:
    def __init__(self):
        self.reconcile_calls = 0

    def get_module_health(self, limit: int = 12):
        return {
            "summary": {"active_modules": 1, "healthy": 1, "failing": 0, "unknown": 0, "circuit_open": 0},
            "modules": [],
        }

    def reconcile_module_tasks(self):
        self.reconcile_calls += 1
        return {"groups": 0, "removed_count": 0, "removed_ids": [], "kept_ids": []}


@pytest.mark.asyncio
async def test_autopilot_tick_collects_actions_and_learning(monkeypatch, tmp_path):
    monkeypatch.setattr("core.autopilot.resolve_elyan_data_dir", lambda: tmp_path)

    from core.autopilot import AutopilotEngine
    from core.predictive_maintenance import PredictionSeverity

    maintenance = FakeMaintenance()
    briefing = FakeBriefingManager()
    suggestions = FakeSuggestionEngine()
    predictive = FakePredictiveMaintenance()
    interventions = FakeInterventionManager()
    device_sync = FakeDeviceSyncStore()
    task_brain = FakeTaskBrain()
    learning = FakeLearningControl()
    automation = FakeAutomationRegistry()

    predictive.predictions = [
        SimpleNamespace(severity=PredictionSeverity.CRITICAL, prevention_action="clear_cache")
    ]

    engine = AutopilotEngine(
        config={
            "tick_interval_seconds": 1,
            "maintenance_interval_seconds": 1,
            "briefing_interval_seconds": 1,
            "suggestion_interval_seconds": 1,
            "task_review_interval_seconds": 1,
            "intervention_interval_seconds": 1,
            "automation_health_interval_seconds": 1,
            "reconcile_interval_seconds": 1,
        },
        maintenance_engine=maintenance,
        briefing_manager=briefing,
        suggestion_engine=suggestions,
        predictive_maintenance=predictive,
        intervention_manager=interventions,
        device_sync_store=device_sync,
        learning_control=learning,
        task_brain_store=task_brain,
        automation_registry_store=automation,
    )

    status_before = engine.get_status()
    assert status_before["running"] is False

    await engine.start(agent=SimpleNamespace(), notify_callback=None)
    await asyncio.sleep(0)
    await engine.stop()

    result = await engine.run_tick(reason="manual_test")
    assert result["running"] is False
    assert maintenance.calls >= 1
    assert predictive.last_action == "clear_cache"
    assert automation.reconcile_calls >= 1
    assert learning.feedback_events
    assert result["last_actions"]
    assert any(action["kind"] == "maintenance" for action in result["last_actions"])
    assert any(action["kind"] == "briefing" for action in result["last_actions"])


def test_autopilot_status_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr("core.autopilot.resolve_elyan_data_dir", lambda: tmp_path)

    from core.autopilot import AutopilotEngine

    engine = AutopilotEngine(
        maintenance_engine=FakeMaintenance(),
        briefing_manager=FakeBriefingManager(),
        suggestion_engine=FakeSuggestionEngine(),
        predictive_maintenance=FakePredictiveMaintenance(),
        intervention_manager=FakeInterventionManager(),
        device_sync_store=FakeDeviceSyncStore(),
        learning_control=FakeLearningControl(),
        task_brain_store=FakeTaskBrain(),
        automation_registry_store=FakeAutomationRegistry(),
    )

    status = engine.status()
    assert status["enabled"] is True
    assert status["running"] is False
    assert "maintenance" in status
    assert "predictive" in status
