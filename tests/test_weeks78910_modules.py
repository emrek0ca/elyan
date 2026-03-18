"""
Weeks 7-10 Performance, Security & Compliance Tests
"""

import pytest
from core.latency_optimizer import LatencyOptimizer
from core.token_optimizer import TokenOptimizer
from core.compliance_engine import ComplianceEngine
from core.disaster_recovery import DisasterRecovery


class TestLatencyOptimizer:
    def test_cache_result(self):
        opt = LatencyOptimizer()
        opt.cache_result("key1", "value1")
        assert opt.get_cached("key1") == "value1"

    def test_register_fast_path(self):
        opt = LatencyOptimizer()
        opt.register_fast_path("test", lambda x: "fast")
        assert "test" in opt.fast_paths

    def test_get_performance_stats(self):
        opt = LatencyOptimizer()
        opt.execution_times.append(50.0)
        stats = opt.get_performance_stats()
        assert "avg_latency_ms" in stats


class TestTokenOptimizer:
    def test_compress_prompt(self):
        opt = TokenOptimizer()
        compressed, ratio = opt.compress_prompt("the quick brown fox")
        assert len(compressed) < len("the quick brown fox")
        assert ratio > 0

    def test_batch_requests(self):
        opt = TokenOptimizer()
        result = opt.batch_requests(["request1", "request2"])
        assert result["request_count"] == 2

    def test_cost_analysis(self):
        opt = TokenOptimizer()
        opt.total_tokens_saved = 1000
        analysis = opt.get_cost_analysis()
        assert "estimated_cost_saved_usd" in analysis


class TestComplianceEngine:
    def test_soc2_compliance(self):
        engine = ComplianceEngine()
        result = engine.check_soc2_compliance()
        assert "soc2_compliant" in result

    def test_gdpr_compliance(self):
        engine = ComplianceEngine()
        result = engine.check_gdpr_compliance()
        assert "gdpr_compliant" in result

    def test_audit_log(self):
        engine = ComplianceEngine()
        engine.log_audit_event("test_action", "user1", {})
        assert len(engine.audit_log) == 1

    def test_compliance_report(self):
        engine = ComplianceEngine()
        report = engine.get_compliance_report()
        assert "soc2" in report
        assert "gdpr" in report


class TestDisasterRecovery:
    def test_create_backup(self):
        dr = DisasterRecovery()
        backup_id = dr.create_backup({"data": "test"})
        assert backup_id is not None

    def test_restore_backup(self):
        dr = DisasterRecovery()
        backup_id = dr.create_backup({"data": "test"})
        result = dr.restore_from_backup(backup_id)
        assert result["restored"] is True

    def test_recovery_metrics(self):
        dr = DisasterRecovery()
        metrics = dr.get_recovery_metrics()
        assert "rto_target_seconds" in metrics

    def test_recovery_test(self):
        dr = DisasterRecovery()
        backup_id = dr.create_backup({"data": "test"})
        result = dr.test_recovery(backup_id)
        assert result["test_passed"] is True
