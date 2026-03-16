#!/usr/bin/env python3
"""
Phase 2 Integration Verification Script

Validates that all new systems are properly integrated and working.
Performs smoke tests and generates integration report.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("phase2_verification")


class IntegrationVerifier:
    """Verifies Phase 2 integration"""

    def __init__(self):
        self.results: Dict[str, Dict] = {}
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0

    def record_test(self, category: str, test_name: str, passed: bool, message: str = ""):
        """Record test result"""
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
            status = "✓ PASS"
        else:
            self.failed_tests += 1
            status = "✗ FAIL"

        if category not in self.results:
            self.results[category] = {}

        self.results[category][test_name] = {
            "passed": passed,
            "message": message,
            "status": status,
        }

        logger.info(f"{status}: {category}/{test_name} - {message}")

    def test_imports(self) -> bool:
        """Test all new modules can be imported"""
        modules_to_test = [
            ("core.tool_schemas_registry", ["get_schema_registry", "ParameterType"]),
            ("core.agent_integration_adapter", ["get_agent_adapter", "AgentIntegrationAdapter"]),
            ("core.reliability_integration", ["validate_before_execution", "get_execution_tracker"]),
            ("core.json_repair", ["JSONRepair"]),
            ("core.llm_orchestrator", ["LLMOrchestrator"]),
            ("core.training_system", ["get_training_system"]),
            ("core.analytics_engine", ["AnalyticsEngine"]),
            ("core.intent.intent_router", ["IntentRouter", "initialize_router"]),
            ("core.intent.tier1_fast_match", ["FastMatcher"]),
            ("core.intent.tier2_semantic_classifier", ["SemanticClassifier"]),
            ("core.intent.tier3_deep_reasoning", ["DeepReasoner"]),
            ("core.intent.user_intent_memory", ["UserIntentMemory"]),
        ]

        all_passed = True

        for module_name, symbols in modules_to_test:
            try:
                module = __import__(module_name, fromlist=symbols)
                for symbol in symbols:
                    if not hasattr(module, symbol):
                        self.record_test(
                            "Imports",
                            f"{module_name}.{symbol}",
                            False,
                            f"Symbol not found"
                        )
                        all_passed = False
                    else:
                        self.record_test(
                            "Imports",
                            f"{module_name}.{symbol}",
                            True,
                            "Imported successfully"
                        )

            except ImportError as e:
                self.record_test(
                    "Imports",
                    module_name,
                    False,
                    f"Import error: {e}"
                )
                all_passed = False

        return all_passed

    def test_schema_registry(self) -> bool:
        """Test schema registry functionality"""
        try:
            from core.tool_schemas_registry import (
                get_schema_registry,
                ToolSchema,
                ParameterSchema,
                ParameterType,
            )

            registry = get_schema_registry()

            # Test registry initialization
            self.record_test(
                "Schema Registry",
                "Initialization",
                registry is not None,
                f"Registry has {len(registry.schemas)} schemas"
            )

            # Test schema retrieval
            schema = registry.get("write_file")
            self.record_test(
                "Schema Registry",
                "Schema retrieval",
                schema is not None,
                "write_file schema found"
            )

            # Test parameter validation
            if schema:
                valid, errors = schema.validate_params({
                    "path": "/tmp/test.txt",
                    "content": "hello world"
                })
                self.record_test(
                    "Schema Registry",
                    "Parameter validation",
                    valid,
                    f"Valid params accepted"
                )

                # Test invalid params
                valid, errors = schema.validate_params({"path": "/tmp/test.txt"})
                self.record_test(
                    "Schema Registry",
                    "Invalid parameter rejection",
                    not valid,
                    f"Invalid params rejected: {errors[0] if errors else ''}"
                )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("Schema Registry", "Overall", False, str(e))
            return False

    async def test_agent_adapter(self) -> bool:
        """Test agent integration adapter"""
        try:
            from core.agent_integration_adapter import get_agent_adapter

            adapter = get_agent_adapter()
            self.record_test(
                "Agent Adapter",
                "Instantiation",
                adapter is not None,
                "Adapter created"
            )

            # Test initialization
            initialized = await adapter.initialize()
            self.record_test(
                "Agent Adapter",
                "Initialization",
                initialized,
                "Adapter initialized"
            )

            # Test LLM provider selection
            provider = adapter.get_best_llm_provider(tier="tier1")
            self.record_test(
                "Agent Adapter",
                "LLM provider selection",
                provider is not None,
                f"Provider selected: {provider}"
            )

            # Test routing stats
            stats = adapter.get_routing_stats()
            self.record_test(
                "Agent Adapter",
                "Routing stats retrieval",
                isinstance(stats, dict),
                f"Stats retrieved: {len(stats)} keys"
            )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("Agent Adapter", "Overall", False, str(e))
            return False

    def test_json_repair(self) -> bool:
        """Test JSON repair functionality"""
        try:
            from core.json_repair import JSONRepair

            test_cases = [
                ('{"valid": "json"}', True),
                ('{"incomplete": "json"', True),  # Should repair
                ('not json at all', False),  # Should fail gracefully
                ('{"nested": {"works": true}}', True),
            ]

            for json_str, should_succeed in test_cases:
                success, result, log = JSONRepair.repair_and_parse(json_str)
                self.record_test(
                    "JSON Repair",
                    f"Repair: {json_str[:20]}...",
                    success == should_succeed,
                    f"Repair {'succeeded' if success else 'failed'}" + (f", log: {log}" if log else "")
                )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("JSON Repair", "Overall", False, str(e))
            return False

    async def test_intent_router(self) -> bool:
        """Test intent router"""
        try:
            from core.intent.intent_router import IntentRouter

            router = IntentRouter()
            self.record_test(
                "Intent Router",
                "Instantiation",
                router is not None,
                "Router created"
            )

            # Test routing stats
            stats = router.get_stats()
            self.record_test(
                "Intent Router",
                "Stats retrieval",
                isinstance(stats, dict),
                f"Stats: {len(stats)} keys"
            )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("Intent Router", "Overall", False, str(e))
            return False

    def test_execution_tracking(self) -> bool:
        """Test execution tracking"""
        try:
            from core.reliability_integration import get_execution_tracker

            tracker = get_execution_tracker()
            self.record_test(
                "Execution Tracking",
                "Tracker initialization",
                tracker is not None,
                "Tracker created"
            )

            # Test start execution
            exec_id = tracker.start_execution("test_id", "test_task", "user123")
            self.record_test(
                "Execution Tracking",
                "Start execution",
                exec_id is not None,
                f"Execution started: {str(exec_id)[:20]}..."
            )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("Execution Tracking", "Overall", False, str(e))
            return False

    async def test_validation(self) -> bool:
        """Test validation system"""
        try:
            from core.reliability_integration import validate_before_execution, create_execution_context

            context = create_execution_context(user_id="test_user")
            self.record_test(
                "Validation",
                "Context creation",
                context is not None,
                "Validation context created"
            )

            # Test validation
            is_valid, error = validate_before_execution(
                "write_file",
                "execute",
                {"path": "/tmp/test.txt", "content": "hello"},
                context
            )
            self.record_test(
                "Validation",
                "Pre-execution validation",
                is_valid,
                f"Validation {'passed' if is_valid else 'failed'}"
            )

            return self.failed_tests == 0

        except Exception as e:
            self.record_test("Validation", "Overall", False, str(e))
            return False

    def print_report(self):
        """Print integration report"""
        print("\n" + "=" * 80)
        print("PHASE 2 INTEGRATION VERIFICATION REPORT")
        print("=" * 80)
        print(f"\nTotal Tests: {self.total_tests}")
        print(f"Passed: {self.passed_tests}")
        print(f"Failed: {self.failed_tests}")
        print(f"Success Rate: {100 * self.passed_tests / self.total_tests:.1f}%")

        print("\n" + "-" * 80)
        print("DETAILED RESULTS")
        print("-" * 80)

        for category in sorted(self.results.keys()):
            print(f"\n{category}:")
            for test_name, result in sorted(self.results[category].items()):
                status = result["status"]
                message = result["message"]
                print(f"  {status}: {test_name}")
                if message:
                    print(f"         {message}")

        print("\n" + "=" * 80)
        if self.failed_tests == 0:
            print("✓ ALL TESTS PASSED - PHASE 2 INTEGRATION SUCCESSFUL")
        else:
            print(f"✗ {self.failed_tests} TESTS FAILED - REVIEW ERRORS ABOVE")
        print("=" * 80 + "\n")

        return self.failed_tests == 0

    async def run_all_tests(self) -> bool:
        """Run all verification tests"""
        logger.info("Starting Phase 2 Integration Verification...")
        print("\nRunning Phase 2 Integration Tests...\n")

        # Run tests
        tests_passed = True

        logger.info("Testing imports...")
        tests_passed &= self.test_imports()

        logger.info("Testing schema registry...")
        tests_passed &= self.test_schema_registry()

        logger.info("Testing JSON repair...")
        tests_passed &= self.test_json_repair()

        logger.info("Testing execution tracking...")
        tests_passed &= self.test_execution_tracking()

        logger.info("Testing validation...")
        tests_passed &= await self.test_validation()

        logger.info("Testing intent router...")
        tests_passed &= await self.test_intent_router()

        logger.info("Testing agent adapter...")
        tests_passed &= await self.test_agent_adapter()

        # Print report
        self.print_report()

        return tests_passed


async def main():
    """Main entry point"""
    verifier = IntegrationVerifier()
    success = await verifier.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
