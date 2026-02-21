
import pytest
from unittest.mock import patch
from core.monitoring import (
    ResourceMonitor,
    get_monitoring,
    record_operation,
    record_error,
)

def test_monitoring_healthy():
    monitor = ResourceMonitor()
    with (patch("psutil.cpu_percent", return_value=10.0),
          patch("psutil.virtual_memory") as mock_mem,
          patch("psutil.disk_usage") as mock_disk,
          patch("psutil.sensors_battery", return_value=None)):
        
        mock_mem.return_value.percent = 20.0
        mock_disk.return_value.percent = 30.0
        
        health = monitor.get_health_snapshot()
        assert health.status == "healthy"
        assert len(health.issues) == 0

def test_monitoring_critical_cpu():
    monitor = ResourceMonitor()
    with (patch("psutil.cpu_percent", return_value=98.0),
          patch("psutil.virtual_memory") as mock_mem,
          patch("psutil.disk_usage") as mock_disk,
          patch("psutil.sensors_battery", return_value=None)):
        
        mock_mem.return_value.percent = 20.0
        mock_disk.return_value.percent = 30.0
        
        health = monitor.get_health_snapshot()
        assert health.status == "critical"
        assert any("CPU" in issue for issue in health.issues)

def test_monitoring_warning_battery():
    monitor = ResourceMonitor()
    with (patch("psutil.cpu_percent", return_value=10.0),
          patch("psutil.virtual_memory") as mock_mem,
          patch("psutil.disk_usage") as mock_disk,
          patch("psutil.sensors_battery") as mock_batt):
        
        mock_mem.return_value.percent = 20.0
        mock_disk.return_value.percent = 30.0
        mock_batt.return_value.percent = 10.0
        mock_batt.return_value.power_plugged = False
        
        health = monitor.get_health_snapshot()
        assert health.status == "warning"
        assert any("Pil" in issue for issue in health.issues)


def test_monitoring_tracker_records_operation_and_error():
    tracker = get_monitoring()
    before = tracker.get_snapshot()

    record_operation(
        operation="task_execution",
        success=True,
        duration_ms=42,
        metadata={"task_count": 2},
    )
    record_error(
        component="task_engine",
        error_msg="boom",
        error_type="task_execution_error",
    )

    after = tracker.get_snapshot()
    assert after["operations_total"] >= before["operations_total"] + 1
    assert after["errors_total"] >= before["errors_total"] + 1
    assert after["last_operation"]["operation"] == "task_execution"
    assert after["last_error"]["component"] == "task_engine"
