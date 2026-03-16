#!/usr/bin/env python3
"""
Verification Script - Validate Learning & Multi-LLM System

Tests all components and validates installation.
"""

import sys
import time
from pathlib import Path

# Add bot root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.analytics_engine import get_analytics_engine
from core.llm_orchestrator import get_llm_orchestrator, LLMProvider
from core.llm_response_quality import get_response_evaluator, ResponseFormat
from core.training_system import get_training_system, TrainingExample
from utils.logger import get_logger

logger = get_logger("verify_system")


def print_header(text: str) -> None:
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def verify_analytics_engine() -> bool:
    """Verify analytics engine"""
    print_header("Verifying Analytics Engine")

    try:
        analytics = get_analytics_engine()

        # Test recording
        analytics.record_execution(
            tool="test_tool",
            intent="test",
            duration_ms=100,
            success=True,
            complexity=0.5
        )
        print("✓ Record execution")

        # Test tool analytics
        tool_metrics = analytics.get_tool_analytics("test_tool")
        assert tool_metrics is not None
        print("✓ Get tool analytics")

        # Test user interaction
        analytics.record_user_interaction(
            user_id="test_user",
            tool_used="test_tool",
            intent="test",
            duration_ms=100,
            language="tr"
        )
        print("✓ Record user interaction")

        # Test LLM call recording
        analytics.record_llm_call(
            provider="groq",
            model="llama-3.3-70b-versatile",
            success=True,
            latency_ms=150,
            cost_usd=0.0001,
            tokens=50,
            quality_score=0.8
        )
        print("✓ Record LLM call")

        # Test insights
        insights = analytics.generate_insights()
        assert "recommendations" in insights
        print("✓ Generate insights")

        # Test dashboard
        dashboard = analytics.get_dashboard_metrics()
        assert "execution_metrics" in dashboard
        print("✓ Generate dashboard metrics")

        print("\n✅ Analytics Engine: PASSED")
        return True

    except Exception as e:
        logger.error(f"Analytics verification failed: {e}", exc_info=True)
        print(f"\n❌ Analytics Engine: FAILED - {e}")
        return False


def verify_llm_orchestrator() -> bool:
    """Verify LLM orchestrator"""
    print_header("Verifying LLM Orchestrator")

    try:
        orchestrator = get_llm_orchestrator()

        # Test provider initialization
        assert len(orchestrator.providers) == len(LLMProvider)
        print(f"✓ Initialized {len(LLMProvider)} providers")

        # Test cost tracker
        orchestrator.cost_tracker.record_cost(0.01)
        assert orchestrator.cost_tracker.daily_cost >= 0.01
        print("✓ Cost tracking")

        # Test budget enforcement
        orchestrator.set_budget_limits(daily=100, monthly=1000)
        assert orchestrator.cost_tracker.check_budget(0.05)
        print("✓ Budget enforcement")

        # Test provider selection
        provider = orchestrator.select_provider(priority="cost")
        print(f"✓ Provider selection by cost: {provider.value if provider else 'None'}")

        # Test stats
        stats = orchestrator.get_all_stats()
        assert len(stats) == len(LLMProvider)
        print("✓ Get all provider stats")

        print("\n✅ LLM Orchestrator: PASSED")
        return True

    except Exception as e:
        logger.error(f"Orchestrator verification failed: {e}", exc_info=True)
        print(f"\n❌ LLM Orchestrator: FAILED - {e}")
        return False


def verify_response_quality() -> bool:
    """Verify response quality evaluator"""
    print_header("Verifying Response Quality Evaluator")

    try:
        evaluator = get_response_evaluator()

        # Test JSON validation
        json_quality = evaluator.evaluate(
            '{"status": "success"}',
            format_type=ResponseFormat.JSON
        )
        assert json_quality.overall_score > 0.5
        print("✓ JSON quality evaluation")

        # Test Markdown validation
        md_quality = evaluator.evaluate(
            "# Title\n- Item 1\n- Item 2",
            format_type=ResponseFormat.MARKDOWN
        )
        assert md_quality.overall_score > 0.5
        print("✓ Markdown quality evaluation")

        # Test code validation
        code_quality = evaluator.evaluate(
            "def hello():\n    return 'world'",
            format_type=ResponseFormat.CODE
        )
        assert code_quality.overall_score > 0.5
        print("✓ Code quality evaluation")

        # Test comprehensive evaluation
        quality = evaluator.evaluate(
            "This is a test response",
            format_type=ResponseFormat.TEXT,
            keywords=["test", "response"]
        )
        assert quality.overall_score >= 0
        print("✓ Comprehensive quality evaluation")

        # Test acceptability
        assert evaluator.is_acceptable(quality, threshold=0.5)
        print("✓ Quality acceptability check")

        print("\n✅ Response Quality Evaluator: PASSED")
        return True

    except Exception as e:
        logger.error(f"Quality evaluator verification failed: {e}", exc_info=True)
        print(f"\n❌ Response Quality Evaluator: FAILED - {e}")
        return False


def verify_training_system() -> bool:
    """Verify training system"""
    print_header("Verifying Training System")

    try:
        training = get_training_system()

        # Test initialization
        assert training.learning_level is not None
        print("✓ Training system initialized")

        # Test concept progression
        assert training.concept_progression.is_concept_known("greeting")
        print("✓ Concept progression")

        # Test reward system
        initial = training.reward_system.total_rewards
        training.reward_system.reward_success("test", magnitude=1.0)
        assert training.reward_system.total_rewards > initial
        print("✓ Reward system")

        # Test feedback loop
        training.feedback_loop.record_correction(
            user_input="test",
            bot_output="wrong",
            correct_output="right",
            intent="test"
        )
        print("✓ Feedback recording")

        # Test learning from examples
        example = TrainingExample(
            input_text="test input",
            expected_output="test output",
            intent="test",
            success=True,
            timestamp=time.time()
        )
        training.learn_from_example(example)
        print("✓ Learning from examples")

        # Test prediction
        action, confidence = training.get_prediction("test input")
        print(f"✓ Prediction: {action} ({confidence:.0%})")

        # Test progress tracking
        metrics = training.get_learning_metrics()
        assert "learning_level" in metrics
        print("✓ Progress metrics")

        print("\n✅ Training System: PASSED")
        return True

    except Exception as e:
        logger.error(f"Training system verification failed: {e}", exc_info=True)
        print(f"\n❌ Training System: FAILED - {e}")
        return False


def verify_integration() -> bool:
    """Verify integration between systems"""
    print_header("Verifying System Integration")

    try:
        analytics = get_analytics_engine()
        orchestrator = get_llm_orchestrator()
        evaluator = get_response_evaluator()
        training = get_training_system()

        # Test analytics + training integration
        analytics.record_execution("tool", "intent", 100, True, 0.5)
        example = TrainingExample(
            input_text="test",
            expected_output="output",
            intent="intent",
            success=True,
            timestamp=time.time()
        )
        training.learn_from_example(example)
        print("✓ Analytics + Training integration")

        # Test quality evaluation
        response = '{"status": "success"}'
        quality = evaluator.evaluate(response, ResponseFormat.JSON)
        assert quality.overall_score >= 0
        print("✓ Quality evaluation")

        # Test provider + analytics
        orchestrator.cost_tracker.record_cost(0.01)
        stats = orchestrator.get_all_stats()
        assert len(stats) > 0
        print("✓ Provider + Analytics integration")

        print("\n✅ System Integration: PASSED")
        return True

    except Exception as e:
        logger.error(f"Integration verification failed: {e}", exc_info=True)
        print(f"\n❌ System Integration: FAILED - {e}")
        return False


def main() -> int:
    """Run verification"""
    print_header("Learning & Multi-LLM System Verification")

    results = {
        "Analytics Engine": verify_analytics_engine(),
        "LLM Orchestrator": verify_llm_orchestrator(),
        "Response Quality": verify_response_quality(),
        "Training System": verify_training_system(),
        "Integration": verify_integration(),
    }

    print_header("Verification Summary")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ All systems verified successfully!")
        print("\nData locations:")
        print("  • Training DB: ~/.elyan/training.db")
        print("  • Analytics DB: ~/.elyan/analytics.db")
        print("\nQuick start:")
        print("  • python scripts/train_elyan.py")
        print("  • python scripts/benchmark_llm_providers.py")
        print("  • python scripts/analyze_learning_progress.py")
        return 0
    else:
        print(f"\n❌ {total - passed} system(s) failed verification")
        return 1


if __name__ == "__main__":
    sys.exit(main())
