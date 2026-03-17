"""
Tests for Weeks 11-12 modules
- Production Monitoring (PrometheusMetrics, HealthMonitor, AlertManager)
- API Rate Limiting (TokenBucket, RateLimitManager, SLAEnforcer)
- Custom Model Framework (ModelTrainer, ModelRegistry, ModelDeployer)
- Documentation Generator (MarkdownGenerator, HTMLGenerator, DocumentationGenerator)
"""

import pytest
import time
import json
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Imports
from core.production_monitor import (
    PrometheusMetrics, HealthMonitor, AlertManager, PerformanceTracker,
    ProductionMonitor, MetricPoint, HealthCheck, Alert
)
from core.api_rate_limiter import (
    TokenBucket, SlidingWindow, AdaptiveRateLimiter, RateLimitManager,
    SLAEnforcer, APIRateLimiter, RateLimit, RateLimitStrategy
)
from core.custom_model_framework import (
    ModelTrainer, ModelRegistry, ModelDeployer, CustomModelFramework,
    TrainingConfig, TrainingData, ModelMetadata, TrainingMethod, ModelType
)
from core.documentation_generator import (
    DocumentationGenerator, MarkdownGenerator, HTMLGenerator, APIEndpoint,
    GuideSection, OutputFormat
)


# ==================== PRODUCTION MONITORING TESTS ====================

class TestPrometheusMetrics:
    """Test Prometheus metrics collection"""

    def test_record_metric(self):
        """Test metric recording"""
        metrics = PrometheusMetrics()
        metrics.record_metric("test_metric", 42.0)

        result = metrics.get_metric("test_metric")
        assert len(result) == 1
        assert result[0].value == 42.0

    def test_record_metric_with_labels(self):
        """Test recording metrics with labels"""
        metrics = PrometheusMetrics()
        metrics.record_metric("http_requests", 1.0, {"endpoint": "/api/test", "status": "200"})
        metrics.record_metric("http_requests", 2.0, {"endpoint": "/api/test", "status": "200"})
        metrics.record_metric("http_requests", 3.0, {"endpoint": "/api/other", "status": "404"})

        # Filter by labels
        result = metrics.get_metric("http_requests", {"endpoint": "/api/test"})
        assert len(result) == 2

    def test_metric_summary(self):
        """Test metric summary statistics"""
        metrics = PrometheusMetrics()
        for i in range(10):
            metrics.record_metric("test_metric", float(i))

        summary = metrics.get_metric_summary("test_metric")
        assert summary["count"] == 10
        assert summary["min"] == 0.0
        assert summary["max"] == 9.0
        assert summary["avg"] == 4.5

    def test_metric_retention(self):
        """Test metric retention cleanup"""
        metrics = PrometheusMetrics()
        metrics.retention_period = 0.1  # Very short retention

        metrics.record_metric("test_metric", 1.0)
        time.sleep(0.15)
        metrics.record_metric("test_metric", 2.0)

        # Old metric should be cleaned up
        result = metrics.get_metric("test_metric")
        assert len(result) == 1
        assert result[0].value == 2.0


class TestHealthMonitor:
    """Test health monitoring"""

    def test_record_health(self):
        """Test recording health checks"""
        monitor = HealthMonitor()
        check = HealthCheck("database", "healthy", "Connection OK")
        monitor.record_health(check)

        status = monitor.get_health_status("database")
        assert status["status"] == "healthy"
        assert status["component"] == "database"

    def test_overall_health_status(self):
        """Test overall health status"""
        monitor = HealthMonitor()
        monitor.record_health(HealthCheck("db", "healthy", "OK"))
        monitor.record_health(HealthCheck("cache", "degraded", "Slow"))
        monitor.record_health(HealthCheck("api", "healthy", "OK"))

        status = monitor.get_health_status()
        assert status["status"] == "degraded"

    def test_critical_status(self):
        """Test critical health status"""
        monitor = HealthMonitor()
        monitor.record_health(HealthCheck("db", "healthy", "OK"))
        monitor.record_health(HealthCheck("api", "critical", "Down"))

        status = monitor.get_health_status()
        assert status["status"] == "critical"

    def test_run_health_checks(self):
        """Test running health check functions"""
        monitor = HealthMonitor()

        def check_db():
            return HealthCheck("database", "healthy", "Connection OK")

        def check_cache():
            return HealthCheck("cache", "healthy", "Connection OK")

        results = monitor.run_health_checks({
            "database": check_db,
            "cache": check_cache
        })

        assert len(results) == 2
        assert results["database"]["status"] == "healthy"


class TestAlertManager:
    """Test alert management"""

    def test_create_alert(self):
        """Test creating alerts"""
        manager = AlertManager()
        manager.create_alert("warning", "High CPU usage", "system")

        alerts = manager.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "warning"

    def test_alert_filtering(self):
        """Test filtering alerts by severity"""
        manager = AlertManager()
        manager.create_alert("info", "System started", "system")
        manager.create_alert("warning", "High memory", "system")
        manager.create_alert("critical", "Database down", "database")

        critical = manager.get_alerts(severity="critical")
        assert len(critical) == 1
        assert critical[0]["severity"] == "critical"

    def test_alert_handler(self):
        """Test alert handler dispatch"""
        manager = AlertManager()
        handled_alerts = []

        def handler(alert):
            handled_alerts.append(alert)

        manager.register_alert_handler(handler)
        manager.create_alert("warning", "Test alert", "system")

        assert len(handled_alerts) == 1
        assert handled_alerts[0].severity == "warning"


class TestPerformanceTracker:
    """Test performance tracking"""

    def test_record_operation(self):
        """Test recording operation times"""
        tracker = PerformanceTracker()
        tracker.record_operation("request_handler", 0.05)
        tracker.record_operation("request_handler", 0.10)
        tracker.record_operation("request_handler", 0.15)

        stats = tracker.get_operation_stats("request_handler")
        assert stats["count"] == 3
        assert stats["min"] == 0.05
        assert stats["max"] == 0.15

    def test_percentiles(self):
        """Test percentile calculations"""
        tracker = PerformanceTracker()
        for i in range(100):
            tracker.record_operation("test", float(i) / 100.0)

        stats = tracker.get_operation_stats("test")
        assert "p50" in stats
        assert "p95" in stats
        assert "p99" in stats


class TestProductionMonitor:
    """Test production monitoring"""

    def test_system_health(self):
        """Test getting system health"""
        monitor = ProductionMonitor()
        health = monitor.get_system_health()

        assert "timestamp" in health
        assert "uptime_seconds" in health
        assert "health_status" in health

    def test_record_request(self):
        """Test recording requests"""
        monitor = ProductionMonitor()
        monitor.record_request("/api/users", 0.05, 200, 512)
        monitor.record_request("/api/users", 0.08, 200, 512)

        report = monitor.get_system_health()
        assert len(report["recent_alerts"]) == 0  # No slow requests

    def test_slow_request_alert(self):
        """Test slow request alerting"""
        monitor = ProductionMonitor()
        monitor.record_request("/api/slow", 6.0, 200, 512)

        report = monitor.get_system_health()
        # Slow requests create warnings, not critical alerts
        assert len(report["recent_alerts"]) > 0
        assert any("warning" in alert.get("severity", "").lower() for alert in report["recent_alerts"])


# ==================== API RATE LIMITER TESTS ====================

class TestTokenBucket:
    """Test token bucket rate limiter"""

    def test_allow_request(self):
        """Test request allowance"""
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        assert bucket.allow_request(1.0) is True
        assert bucket.allow_request(9.0) is True
        assert bucket.allow_request(1.0) is False

    def test_refill(self):
        """Test token refilling"""
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
        bucket.allow_request(10.0)
        assert bucket.allow_request(1.0) is False

        time.sleep(1.1)
        assert bucket.allow_request(1.0) is True

    def test_wait_time(self):
        """Test wait time calculation"""
        bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
        bucket.allow_request(5.0)

        wait_time = bucket.get_wait_time(2.0)
        assert wait_time > 1.9


class TestSlidingWindow:
    """Test sliding window rate limiter"""

    def test_sliding_window_limit(self):
        """Test sliding window limiting"""
        window = SlidingWindow(window_size_seconds=1, max_requests=5)

        for _ in range(5):
            assert window.allow_request() is True

        assert window.allow_request() is False

    def test_window_expiry(self):
        """Test window time expiry"""
        window = SlidingWindow(window_size_seconds=1, max_requests=5)

        for _ in range(5):
            window.allow_request()

        time.sleep(1.1)
        assert window.allow_request() is True


class TestAdaptiveRateLimiter:
    """Test adaptive rate limiter"""

    def test_adjust_rate_up(self):
        """Test rate adjustment up"""
        limiter = AdaptiveRateLimiter(initial_rps=10.0)
        initial_rps = limiter.current_rps

        # First adjustment
        limiter.adjust_rate(error_rate=0.005, response_time_ms=50)
        time.sleep(1.1)
        # Second adjustment to actually trigger
        limiter.adjust_rate(error_rate=0.005, response_time_ms=50)

        # Rate should increase due to good health
        assert limiter.current_rps >= initial_rps

    def test_adjust_rate_down(self):
        """Test rate adjustment down"""
        limiter = AdaptiveRateLimiter(initial_rps=10.0)
        initial_rps = limiter.current_rps

        # First adjustment
        limiter.adjust_rate(error_rate=0.1, response_time_ms=2000)
        time.sleep(1.1)
        # Second adjustment to actually trigger
        limiter.adjust_rate(error_rate=0.1, response_time_ms=2000)

        # Rate should decrease due to poor health
        assert limiter.current_rps < initial_rps


class TestRateLimitManager:
    """Test rate limit management"""

    def test_check_limit(self):
        """Test checking rate limits"""
        manager = RateLimitManager()
        limit = RateLimit("api", 60, strategy=RateLimitStrategy.TOKEN_BUCKET)
        manager.add_limit("client1", limit)

        allowed, retry_after = manager.check_limit("client1", "api")
        assert allowed is True
        assert retry_after is None

    def test_rate_limit_violation(self):
        """Test recording violations"""
        manager = RateLimitManager()
        limit = RateLimit("api", 1, strategy=RateLimitStrategy.TOKEN_BUCKET)
        manager.add_limit("client1", limit)

        manager.check_limit("client1", "api")
        allowed, retry_after = manager.check_limit("client1", "api")

        assert allowed is False
        assert retry_after is not None

    def test_client_limits(self):
        """Test getting client limits"""
        manager = RateLimitManager()
        limit = RateLimit("api", 60)
        manager.add_limit("client1", limit)

        limits = manager.get_client_limits("client1")
        assert "api" in limits
        assert limits["api"]["requests_per_minute"] == 60


class TestSLAEnforcer:
    """Test SLA enforcement"""

    def test_sla_target(self):
        """Test setting SLA targets"""
        enforcer = SLAEnforcer()
        enforcer.set_sla_target("/api/users", p95_ms=100, p99_ms=200, uptime_pct=99.9, error_rate=0.01)

        # Record some requests
        for _ in range(50):
            enforcer.record_request("/api/users", 50.0, True)

        status = enforcer.check_sla("/api/users")
        assert status["compliant"] is True

    def test_sla_violation(self):
        """Test SLA violations"""
        enforcer = SLAEnforcer()
        enforcer.set_sla_target("/api/users", p95_ms=50, p99_ms=100, uptime_pct=99.9, error_rate=0.01)

        # Record slow requests
        for _ in range(50):
            enforcer.record_request("/api/users", 200.0, True)

        status = enforcer.check_sla("/api/users")
        assert status["compliant"] is False
        assert len(status["violations"]) > 0


# ==================== CUSTOM MODEL FRAMEWORK TESTS ====================

class TestTrainingConfig:
    """Test training configuration"""

    def test_config_creation(self):
        """Test creating training config"""
        config = TrainingConfig(
            base_model="meta-llama/Llama-2-7b",
            method=TrainingMethod.QLORA
        )

        assert config.base_model == "meta-llama/Llama-2-7b"
        assert config.method == TrainingMethod.QLORA

    def test_config_to_dict(self):
        """Test converting config to dict"""
        config = TrainingConfig(
            base_model="gpt2",
            method=TrainingMethod.PEFT_LORA
        )

        config_dict = config.to_dict()
        assert config_dict["base_model"] == "gpt2"
        assert config_dict["method"] == "peft_lora"


class TestModelTrainer:
    """Test model trainer"""

    def test_start_training(self, tmp_path):
        """Test starting training job"""
        trainer = ModelTrainer(str(tmp_path))
        config = TrainingConfig("gpt2", TrainingMethod.PEFT_LORA)
        training_data = TrainingData([
            {"input": "Hello", "output": "Hi there", "instruction": "Say hello"},
            {"input": "How are you", "output": "I'm good", "instruction": "Respond"}
        ])

        job_id = trainer.start_training("test_model", training_data, config)
        assert job_id.startswith("test_model_")

    def test_training_status(self, tmp_path):
        """Test getting training status"""
        trainer = ModelTrainer(str(tmp_path))
        config = TrainingConfig("gpt2", TrainingMethod.PEFT_LORA)
        training_data = TrainingData([{"input": "test", "output": "test", "instruction": "test"}])

        job_id = trainer.start_training("model", training_data, config)
        status = trainer.get_training_status(job_id)

        assert status["model_id"] == "model"
        assert status["status"] == "queued"


class TestModelRegistry:
    """Test model registry"""

    def test_register_model(self, tmp_path):
        """Test registering a model"""
        registry = ModelRegistry(str(tmp_path))
        metadata = ModelMetadata(
            model_id="test_model",
            name="Test Model",
            description="A test model",
            base_model="gpt2",
            model_type=ModelType.INSTRUCTION_TUNED,
            training_method=TrainingMethod.PEFT_LORA
        )

        version_dir = tmp_path / "test_model" / "v1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)

        registry.register_model(metadata, version_dir)
        assert "test_model" in registry.models

    def test_list_models(self, tmp_path):
        """Test listing models"""
        registry = ModelRegistry(str(tmp_path))
        metadata = ModelMetadata(
            model_id="model1",
            name="Model 1",
            description="Test",
            base_model="gpt2",
            model_type=ModelType.CODE,
            training_method=TrainingMethod.FULL_FINE_TUNE
        )

        version_dir = tmp_path / "model1" / "v1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)
        registry.register_model(metadata, version_dir)

        models = registry.list_models()
        assert "model1" in models


class TestModelDeployer:
    """Test model deployment"""

    def test_deploy_model(self, tmp_path):
        """Test deploying a model"""
        registry = ModelRegistry(str(tmp_path))
        metadata = ModelMetadata(
            model_id="deploy_test",
            name="Deploy Test",
            description="Test",
            base_model="gpt2",
            model_type=ModelType.CHAT,
            training_method=TrainingMethod.PEFT_LORA,
            status="ready"
        )

        version_dir = tmp_path / "deploy_test" / "v1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)
        registry.register_model(metadata, version_dir)

        deployer = ModelDeployer(registry)
        assert deployer.deploy_model("deploy_test") is True

        deployed = deployer.get_deployed_models()
        assert "deploy_test" in deployed

    def test_undeploy_model(self, tmp_path):
        """Test undeploying a model"""
        registry = ModelRegistry(str(tmp_path))
        metadata = ModelMetadata(
            model_id="model",
            name="Model",
            description="Test",
            base_model="gpt2",
            model_type=ModelType.CHAT,
            training_method=TrainingMethod.PEFT_LORA
        )

        version_dir = tmp_path / "model" / "v1.0.0"
        version_dir.mkdir(parents=True, exist_ok=True)
        registry.register_model(metadata, version_dir)

        deployer = ModelDeployer(registry)
        deployer.deploy_model("model")
        assert deployer.undeploy_model("model") is True


# ==================== DOCUMENTATION GENERATOR TESTS ====================

class TestMarkdownGenerator:
    """Test Markdown documentation generation"""

    def test_generate_api_docs(self):
        """Test generating API docs"""
        endpoints = [
            APIEndpoint(
                name="Get Users",
                method="GET",
                path="/api/users",
                description="Get all users",
                parameters=[
                    {"name": "limit", "type": "int", "description": "Limit results"}
                ],
                response={"users": [], "count": 0}
            )
        ]

        docs = MarkdownGenerator.generate_api_docs(endpoints)
        assert "Get Users" in docs
        assert "GET" in docs
        assert "/api/users" in docs

    def test_generate_guide(self):
        """Test generating guide"""
        sections = [
            GuideSection(
                title="Getting Started",
                content="Start here",
                code_examples=[
                    {"description": "Basic usage", "code": "import elyan"}
                ]
            )
        ]

        guide = MarkdownGenerator.generate_guide(sections)
        assert "Getting Started" in guide
        assert "Basic usage" in guide


class TestDocumentationGenerator:
    """Test documentation generator"""

    def test_generate_api_documentation(self, tmp_path):
        """Test generating API documentation"""
        gen = DocumentationGenerator(str(tmp_path))
        endpoints = [
            APIEndpoint(
                name="Health Check",
                method="GET",
                path="/health",
                description="Check system health",
                parameters=[],
                response={"status": "ok"}
            )
        ]

        output_file = gen.generate_api_documentation(endpoints)
        assert Path(output_file).exists()

    def test_generate_guide(self, tmp_path):
        """Test generating guide"""
        gen = DocumentationGenerator(str(tmp_path))
        sections = [
            GuideSection(
                title="Introduction",
                content="Introduction to Elyan"
            )
        ]

        output_file = gen.generate_guide("User Guide", sections)
        assert Path(output_file).exists()

    def test_training_materials(self, tmp_path):
        """Test generating training materials"""
        gen = DocumentationGenerator(str(tmp_path))
        materials = gen.generate_training_materials()

        assert "quick_start" in materials
        assert "best_practices" in materials
        assert "api_reference" in materials


# ==================== INTEGRATION TESTS ====================

class TestProductionMonitorIntegration:
    """Integration tests for production monitor"""

    def test_full_monitoring_flow(self):
        """Test complete monitoring workflow"""
        monitor = ProductionMonitor()

        # Record health
        monitor.health.record_health(HealthCheck("api", "healthy", "OK"))

        # Record request
        monitor.record_request("/api/test", 0.05, 200, 256)

        # Get system report
        report = monitor.get_system_health()
        assert "health_status" in report
        assert report["health_status"]["status"] == "healthy"

    def test_prometheus_export(self):
        """Test Prometheus metrics export"""
        monitor = ProductionMonitor()
        monitor.metrics.record_metric("test_metric", 42.0)

        prometheus_format = monitor.get_prometheus_format()
        assert "test_metric" in prometheus_format
        assert "42.0" in prometheus_format


class TestAPIRateLimiterIntegration:
    """Integration tests for rate limiter"""

    def test_full_rate_limiting(self):
        """Test complete rate limiting flow"""
        limiter = APIRateLimiter()

        # Configure client
        limits = [
            RateLimit("api_endpoint", 60, burst_size=10)
        ]
        limiter.configure_client("client1", limits)

        # Make requests
        allowed_count = 0
        for _ in range(70):
            allowed, _ = limiter.check_request("client1", "api_endpoint")
            if allowed:
                allowed_count += 1

        assert allowed_count <= 60

    def test_sla_enforcement(self):
        """Test SLA enforcement"""
        limiter = APIRateLimiter()
        limiter.sla_enforcer.set_sla_target("/api/test", 100, 200, 99.5, 0.01)

        for _ in range(100):
            limiter.record_request("client1", "/api/test", 50.0, True)

        status = limiter.get_status()
        assert status is not None


class TestCustomModelWorkflow:
    """Integration tests for custom model framework"""

    def test_complete_model_workflow(self, tmp_path):
        """Test complete model creation and deployment"""
        framework = CustomModelFramework(str(tmp_path))

        # Create training data
        training_data = TrainingData([
            {"input": "What is 2+2?", "output": "4", "instruction": "Answer math"},
            {"input": "What is 3+3?", "output": "6", "instruction": "Answer math"}
        ])

        # Create training config
        config = TrainingConfig(
            base_model="gpt2",
            method=TrainingMethod.PEFT_LORA
        )

        # Start training
        job_id = framework.create_and_train_model(
            "math_tutor",
            "Math Tutor",
            "gpt2",
            training_data,
            config
        )

        assert job_id is not None

        # Check status
        status = framework.get_status()
        assert "registered_models" in status


# ==================== EDGE CASE AND ERROR TESTS ====================

class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_metrics(self):
        """Test handling empty metrics"""
        metrics = PrometheusMetrics()
        summary = metrics.get_metric_summary("nonexistent")
        assert "error" in summary

    def test_invalid_health_component(self):
        """Test handling invalid health component"""
        monitor = HealthMonitor()
        status = monitor.get_health_status("nonexistent")
        assert "error" in status

    def test_rate_limit_negative_wait(self):
        """Test negative wait time handling"""
        bucket = TokenBucket(10.0, 1.0)
        bucket.tokens = 10.0
        wait_time = bucket.get_wait_time()
        assert wait_time >= 0.0

    def test_multiple_concurrent_alerts(self):
        """Test handling multiple alerts"""
        manager = AlertManager(max_alerts=5)
        for i in range(10):
            manager.create_alert("info", f"Alert {i}", "system")

        # Should only keep last 5
        alerts = manager.get_alerts(limit=100)
        assert len(alerts) <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
