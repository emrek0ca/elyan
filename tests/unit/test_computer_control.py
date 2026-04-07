"""Tests for Computer Control modules."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAppController:
    @pytest.mark.asyncio
    async def test_get_battery_info_parsing(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        mock_out = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=...) 78%; discharging; 2:34 remaining"
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(True, mock_out))):
            info = await ctrl.get_battery_info()
        assert info["percent"] == 78
        assert info["charging"] is False

    @pytest.mark.asyncio
    async def test_get_battery_charging(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        mock_out = "Now drawing from 'AC Power'\n -InternalBattery-0 100%; charging"
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(True, mock_out))):
            info = await ctrl.get_battery_info()
        assert info["charging"] is True

    @pytest.mark.asyncio
    async def test_get_disk_usage_parsing(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        mock_out = "Filesystem  1K-blocks       Used Available Use% Mounted\n/dev/disk1  976784384  512000000  464784384  53% /"
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(True, mock_out))):
            info = await ctrl.get_disk_usage()
        assert info["total_gb"] > 0
        assert info["free_gb"] > 0
        assert 0 <= info["used_pct"] <= 100

    @pytest.mark.asyncio
    async def test_get_cpu_usage_parsing(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        mock_out = "CPU usage: 12.5% user, 8.3% sys, 79.2% idle"
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(True, mock_out))):
            usage = await ctrl.get_cpu_usage()
        assert abs(usage - 20.8) < 0.1

    @pytest.mark.asyncio
    async def test_clipboard(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(True, ""))):
            ok = await ctrl.set_clipboard("hello")
        assert ok is True

    @pytest.mark.asyncio
    async def test_graceful_failure(self):
        from core.computer.app_controller import AppController
        ctrl = AppController()
        with patch("core.computer.app_controller._run", new=AsyncMock(return_value=(False, ""))):
            info = await ctrl.get_battery_info()
        assert isinstance(info, dict)


class TestSchedulerAgent:
    def test_is_due_interval(self):
        import time
        from core.proactive.scheduler_agent import ScheduledTask, _is_due
        task = ScheduledTask("t1", "test", "*/1m", AsyncMock(), last_run_ts=time.time() - 65)
        assert _is_due(task) is True

    def test_not_due_interval(self):
        import time
        from core.proactive.scheduler_agent import ScheduledTask, _is_due
        task = ScheduledTask("t2", "test", "*/5m", AsyncMock(), last_run_ts=time.time() - 30)
        assert _is_due(task) is False

    def test_register_unregister(self):
        from core.proactive.scheduler_agent import SchedulerAgent, ScheduledTask
        agent = SchedulerAgent()
        task = ScheduledTask("t1", "daily", "09:00", AsyncMock())
        agent.register(task)
        assert "t1" in agent._tasks
        agent.unregister("t1")
        assert "t1" not in agent._tasks


class TestSystemMonitor:
    def test_builtin_rules_registered(self):
        from core.proactive.system_monitor import SystemMonitor
        monitor = SystemMonitor()
        rule_ids = {r.rule_id for r in monitor._rules}
        assert "cpu_high" in rule_ids
        assert "battery_critical" in rule_ids
        assert "disk_low" in rule_ids

    @pytest.mark.asyncio
    async def test_alert_handler_called(self):
        from core.proactive.system_monitor import SystemMonitor, MonitorRule
        monitor = SystemMonitor()
        monitor._rules = []  # clear builtin rules

        fired = []
        async def handler(alert):
            fired.append(alert)

        monitor.register_alert_handler(handler)
        monitor.register_rule(MonitorRule(
            "test_rule",
            check_fn=AsyncMock(return_value=True),
            severity="warning",
            title="Test Alert",
            message="Test message",
        ))
        await monitor._check_once()
        assert len(fired) == 1
        assert fired[0].title == "Test Alert"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self):
        import time
        from core.proactive.system_monitor import SystemMonitor, MonitorRule
        monitor = SystemMonitor()
        monitor._rules = []
        fired = []
        async def handler(alert):
            fired.append(alert)
        monitor.register_alert_handler(handler)
        monitor.register_rule(MonitorRule(
            "test_cd", check_fn=AsyncMock(return_value=True),
            severity="info", title="CD Test", message="msg", cooldown_s=300,
        ))
        await monitor._check_once()
        await monitor._check_once()  # should be blocked by cooldown
        assert len(fired) == 1


class TestContextTracker:
    @pytest.mark.asyncio
    async def test_tracks_app_switch(self):
        from core.proactive.context_tracker import ContextTracker
        tracker = ContextTracker()
        with patch("core.computer.macos_controller.get_macos_controller") as mock_ctrl:
            mock_ctrl.return_value.get_frontmost_app = AsyncMock(return_value="Safari")
            with patch("core.proactive.context_tracker.get_macos_controller", mock_ctrl):
                await tracker.update()
        assert tracker.get_context().current_app == "Safari"

    @pytest.mark.asyncio
    async def test_recent_apps_history(self):
        from core.proactive.context_tracker import ContextTracker
        tracker = ContextTracker()
        apps = ["Safari", "Xcode", "Terminal"]
        for app in apps:
            with patch("core.proactive.context_tracker.get_macos_controller") as mock_ctrl:
                mock_ctrl.return_value.get_frontmost_app = AsyncMock(return_value=app)
                await tracker.update()
        ctx = tracker.get_context()
        assert "Safari" in ctx.recent_apps or "Xcode" in ctx.recent_apps
