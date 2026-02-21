
import pytest
from unittest.mock import MagicMock, patch
from core.monitoring import ResourceMonitor

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
