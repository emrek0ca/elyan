"""
Tests for Production Components
================================
"""

import pytest
import tempfile
import asyncio
import time
from pathlib import Path
from unittest.mock import Mock, patch

from core.health_checks import (
    HealthCheck,
    DatabaseHealthCheck,
    DiskSpaceHealthCheck,
    MemoryHealthCheck,
    HealthCheckSuite,
    HealthStatus
)

from core.production_logging import (
    ContextLogger,
    PerformanceLogger,
    ProductionLogger,
    ErrorCategorizer
)

from core.alerting import (
    AlertThreshold,
    Alert,
    AlertStore,
    AlertManager,
    AlertSeverity,
    LogNotifier
)


class TestHealthChecks:
    """Tests for health check system."""

    @pytest.mark.asyncio
    async def test_database_health_check_success(self):
        """Test database health check with valid database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db_path.touch()

            check = DatabaseHealthCheck(str(db_path))
            result = await check.execute()

            assert result.status == HealthStatus.HEALTHY.value
            assert "success" in result.message.lower()

    @pytest.mark.asyncio
    async def test_database_health_check_failure(self):
        """Test database health check with invalid database."""
        check = DatabaseHealthCheck("/nonexistent/path/db.db")
        result = await check.execute()

        assert result.status == HealthStatus.UNHEALTHY.value
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_disk_space_health_check(self):
        """Test disk space health check."""
        check = DiskSpaceHealthCheck(path="/", min_mb=1.0)
        result = await check.execute()

        assert result.status in [HealthStatus.HEALTHY.value, HealthStatus.DEGRADED.value]
        assert "available_mb" in result.details

    @pytest.mark.asyncio
    async def test_memory_health_check(self):
        """Test memory health check."""
        check = MemoryHealthCheck(max_percent=99.0)
        result = await check.execute()

        assert result.status in [HealthStatus.HEALTHY.value, HealthStatus.DEGRADED.value]
        assert "percent" in result.details

    @pytest.mark.asyncio
    async def test_health_check_suite(self):
        """Test health check suite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db_path.touch()

            suite = HealthCheckSuite()
            suite.add_check(DatabaseHealthCheck(str(db_path)))
            suite.add_check(MemoryHealthCheck())

            results = await suite.run_all()

            assert "overall_status" in results
            assert results["checks_run"] == 2
            assert "details" in results

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        """Test health check timeout."""
        async def slow_check():
            await asyncio.sleep(10)
            return True

        class SlowHealthCheck(HealthCheck):
            async def _check(self):
                await slow_check()
                return None

        check = SlowHealthCheck("slow", timeout=0.1)
        result = await check.execute()

        assert result.status == HealthStatus.UNHEALTHY.value
        assert "timeout" in result.message.lower()


class TestProductionLogging:
    """Tests for production logging."""

    def test_context_logger_creation(self):
        """Test context logger creation."""
        logger = ContextLogger("test")
        assert logger.logger is not None
        assert len(logger.context) == 0

    def test_context_logger_context(self):
        """Test context setting."""
        logger = ContextLogger("test")
        logger.set_context(user_id="user123", request_id="req456")

        assert logger.context["user_id"] == "user123"
        assert logger.context["request_id"] == "req456"

    def test_context_logger_clear(self):
        """Test clearing context."""
        logger = ContextLogger("test")
        logger.set_context(user_id="user123")
        logger.clear_context()

        assert len(logger.context) == 0

    def test_performance_logger(self):
        """Test performance logger."""
        import logging
        logger = logging.getLogger("perf_test")
        perf_logger = PerformanceLogger(logger)

        perf_logger.start_timer("test_op")
        time.sleep(0.01)
        duration = perf_logger.end_timer("test_op")

        assert duration > 0
        assert duration >= 10  # At least 10ms

    def test_error_categorizer(self):
        """Test error categorization."""
        # Database error
        category = ErrorCategorizer.categorize("DatabaseError", "sqlite connection failed")
        assert category == "database"

        # Network error
        category = ErrorCategorizer.categorize("TimeoutError", "network timeout")
        assert category == "network"

        # Unknown error
        category = ErrorCategorizer.categorize("CustomError", "something went wrong")
        assert category == "unknown"

    def test_error_hash(self):
        """Test error hashing."""
        hash1 = ErrorCategorizer.get_error_hash("DatabaseError", "connection lost")
        hash2 = ErrorCategorizer.get_error_hash("DatabaseError", "connection lost")

        assert hash1 == hash2

        hash3 = ErrorCategorizer.get_error_hash("DatabaseError", "different error")
        assert hash1 != hash3

    def test_production_logger(self):
        """Test production logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_logger = ProductionLogger("test_bot", log_dir=tmpdir)

            assert prod_logger.logger is not None
            assert len(prod_logger.logger.handlers) > 0

            log_files = prod_logger.get_log_files()
            assert len(log_files) > 0

    def test_log_request(self):
        """Test logging HTTP request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_logger = ProductionLogger("test_bot", log_dir=tmpdir)

            prod_logger.log_request(
                request_id="req123",
                method="GET",
                endpoint="/api/status",
                status_code=200,
                duration_ms=45.5
            )

            # Verify log file was written
            log_files = prod_logger.get_log_files()
            assert len(log_files) > 0

    def test_log_task(self):
        """Test logging task execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_logger = ProductionLogger("test_bot", log_dir=tmpdir)

            prod_logger.log_task(
                task_id="task_123",
                status="completed",
                duration_ms=120.5
            )

            log_files = prod_logger.get_log_files()
            assert len(log_files) > 0

    def test_log_error(self):
        """Test logging error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_logger = ProductionLogger("test_bot", log_dir=tmpdir)

            error_hash = prod_logger.log_error(
                error_type="DatabaseError",
                error_message="Connection timeout"
            )

            assert len(error_hash) > 0


class TestAlerting:
    """Tests for alerting system."""

    def test_alert_threshold_creation(self):
        """Test creating alert threshold."""
        threshold = AlertThreshold(
            metric_name="error_rate",
            operator=">",
            threshold_value=5.0,
            severity=AlertSeverity.WARNING.value,
            message_template="Error rate is {value}%"
        )

        assert threshold.metric_name == "error_rate"
        assert threshold.threshold_value == 5.0

    def test_alert_creation(self):
        """Test creating alert."""
        alert = Alert(
            alert_id="alert_1",
            metric_name="error_rate",
            severity=AlertSeverity.WARNING.value,
            message="Error rate high",
            value=7.5,
            threshold=5.0,
            timestamp=time.time()
        )

        assert alert.alert_id == "alert_1"
        assert not alert.resolved

    def test_alert_store(self):
        """Test alert storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "alerts.db")
            store = AlertStore(db_path)

            alert = Alert(
                alert_id="alert_1",
                metric_name="error_rate",
                severity=AlertSeverity.WARNING.value,
                message="Error rate high",
                value=7.5,
                threshold=5.0,
                timestamp=time.time()
            )

            store.save_alert(alert)

            # Retrieve alert
            retrieved = store.get_alert("alert_1")
            assert retrieved is not None
            assert retrieved.alert_id == "alert_1"

    def test_alert_manager(self):
        """Test alert manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "alerts.db")
            manager = AlertManager(db_path)

            threshold = AlertThreshold(
                metric_name="error_rate",
                operator=">",
                threshold_value=5.0,
                severity=AlertSeverity.WARNING.value,
                message_template="Error rate is {value}%"
            )

            manager.add_threshold(threshold)

            # Check metric below threshold
            alert = manager.check_metric("error_rate", 3.0)
            assert alert is None

            # Check metric above threshold
            alert = manager.check_metric("error_rate", 7.5)
            assert alert is not None
            assert alert.severity == AlertSeverity.WARNING.value

    def test_alert_cooldown(self):
        """Test alert cooldown mechanism."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "alerts.db")
            manager = AlertManager(db_path)

            threshold = AlertThreshold(
                metric_name="error_rate",
                operator=">",
                threshold_value=5.0,
                severity=AlertSeverity.WARNING.value,
                message_template="Error rate is {value}%",
                cooldown_minutes=1
            )

            manager.add_threshold(threshold)

            # First alert
            alert1 = manager.check_metric("error_rate", 7.5)
            assert alert1 is not None

            # Second alert should be suppressed by cooldown
            alert2 = manager.check_metric("error_rate", 8.0)
            assert alert2 is None

    def test_alert_statistics(self):
        """Test alert statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "alerts.db")
            store = AlertStore(db_path)

            for i in range(3):
                alert = Alert(
                    alert_id=f"alert_{i}",
                    metric_name="error_rate",
                    severity=AlertSeverity.WARNING.value,
                    message="Error rate high",
                    value=7.5,
                    threshold=5.0,
                    timestamp=time.time()
                )
                store.save_alert(alert)

            stats = store.get_statistics()
            assert stats["active_alerts"] == 3

    def test_log_notifier(self):
        """Test log notification."""
        import logging
        logger = logging.getLogger("alert_test")

        notifier = LogNotifier(logger)

        alert = Alert(
            alert_id="alert_1",
            metric_name="error_rate",
            severity=AlertSeverity.WARNING.value,
            message="Error rate high",
            value=7.5,
            threshold=5.0,
            timestamp=time.time()
        )

        result = notifier.send(alert)
        assert result


class TestProductionScenarios:
    """Integration tests for production scenarios."""

    @pytest.mark.asyncio
    async def test_health_check_full_suite(self):
        """Test full health check suite in production scenario."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db_path.touch()

            suite = HealthCheckSuite()
            suite.add_check(DatabaseHealthCheck(str(db_path)))
            suite.add_check(MemoryHealthCheck(max_percent=99.0))

            results = await suite.run_all()

            assert results["overall_status"] in [
                HealthStatus.HEALTHY.value,
                HealthStatus.DEGRADED.value
            ]

    def test_alert_workflow(self):
        """Test complete alert workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "alerts.db")
            manager = AlertManager(db_path)

            # Add logger notifier
            import logging
            logger = logging.getLogger("alert_workflow")
            manager.add_notifier(LogNotifier(logger))

            # Add threshold
            threshold = AlertThreshold(
                metric_name="latency_p99",
                operator=">",
                threshold_value=5000.0,
                severity=AlertSeverity.CRITICAL.value,
                message_template="P99 latency is {value}ms (threshold: {threshold}ms)"
            )
            manager.add_threshold(threshold)

            # Metric within threshold
            alert = manager.check_metric("latency_p99", 3000.0)
            assert alert is None

            # Metric exceeds threshold
            alert = manager.check_metric("latency_p99", 6000.0)
            assert alert is not None

            # Get active alerts
            active = manager.get_active_alerts()
            assert len(active) == 1

            # Resolve alert
            manager.resolve_alert(active[0].alert_id)

            # Check resolved
            active = manager.get_active_alerts()
            assert len(active) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
