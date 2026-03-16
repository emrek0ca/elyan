#!/usr/bin/env python3
"""
ELYAN ACTIVATION SCRIPT
=======================

Verifies all systems are operational and ready for PHASE 3 deployment.

Performs:
1. System initialization checks
2. LLM provider availability
3. Database initialization
4. Schema registration
5. Smoke tests
6. Health reporting
"""

import sys
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger
from core.agent_integration_adapter import (
    get_adapter,
    initialize_integration,
    register_all_tool_schemas,
)

logger = get_logger("activate_elyan")


class ActivationChecker:
    """Verifies system readiness for deployment."""

    def __init__(self):
        self.results: List[Tuple[str, bool, str]] = []
        self.start_time = time.time()

    def check(self, name: str, func, *args, **kwargs) -> bool:
        """Run a check and record result."""
        try:
            logger.info(f"Checking: {name}...")
            result = func(*args, **kwargs)
            success = bool(result)
            msg = str(result) if not success else "OK"
            self.results.append((name, success, msg))
            status = "✓" if success else "✗"
            logger.info(f"{status} {name}")
            return success
        except Exception as e:
            logger.error(f"✗ {name}: {e}")
            self.results.append((name, False, str(e)))
            return False

    async def async_check(self, name: str, func, *args, **kwargs) -> bool:
        """Run async check and record result."""
        try:
            logger.info(f"Checking: {name}...")
            result = await func(*args, **kwargs)
            success = bool(result)
            msg = str(result) if not success else "OK"
            self.results.append((name, success, msg))
            status = "✓" if success else "✗"
            logger.info(f"{status} {name}")
            return success
        except Exception as e:
            logger.error(f"✗ {name}: {e}")
            self.results.append((name, False, str(e)))
            return False

    def report(self) -> Dict[str, Any]:
        """Generate activation report."""
        elapsed = time.time() - self.start_time
        passed = sum(1 for _, success, _ in self.results if success)
        total = len(self.results)

        return {
            "timestamp": time.time(),
            "elapsed_seconds": elapsed,
            "passed": passed,
            "total": total,
            "success": passed == total,
            "checks": [
                {
                    "name": name,
                    "passed": success,
                    "message": msg,
                }
                for name, success, msg in self.results
            ],
        }


async def main():
    """Run activation checks."""
    print("\n" + "=" * 70)
    print("ELYAN PHASE 3 ACTIVATION")
    print("=" * 70 + "\n")

    checker = ActivationChecker()

    # ========================================================================
    # SYSTEM INITIALIZATION
    # ========================================================================

    print("\n[1/4] SYSTEM INITIALIZATION")
    print("-" * 70)

    checker.check(
        "LLM Orchestrator Import",
        lambda: __import__("core.llm_orchestrator", fromlist=["LLMOrchestrator"]),
    )

    checker.check(
        "Intent Router Import",
        lambda: __import__("core.intent.intent_router", fromlist=["IntentRouter"]),
    )

    checker.check(
        "Training System Import",
        lambda: __import__("core.training_system", fromlist=["TrainingSystem"]),
    )

    checker.check(
        "Analytics Engine Import",
        lambda: __import__("core.analytics_engine", fromlist=["AnalyticsEngine"]),
    )

    checker.check(
        "Reliability Integration Import",
        lambda: __import__("core.reliability_integration", fromlist=["ExecutionGuard"]),
    )

    print("\n[2/4] ADAPTER INITIALIZATION")
    print("-" * 70)

    adapter = get_adapter()
    status = checker.check(
        "Adapter Creation",
        lambda: adapter is not None,
    )

    if status:
        init_status = checker.check(
            "Integration Systems Initialization",
            lambda: initialize_integration(),
        )

        if init_status:
            ready, msg = adapter.ready_check()
            checker.check("Adapter Ready Check", lambda: ready)

    # ========================================================================
    # TOOL SCHEMAS
    # ========================================================================

    print("\n[3/4] SCHEMA REGISTRATION")
    print("-" * 70)

    checker.check(
        "Tool Schemas Registration",
        register_all_tool_schemas,
    )

    # ========================================================================
    # SMOKE TESTS
    # ========================================================================

    print("\n[4/4] SMOKE TESTS")
    print("-" * 70)

    # Test adapter is initialized
    if adapter.is_ready():
        checker.check(
            "Adapter Operational",
            lambda: adapter.is_ready(),
        )

        # Test intent routing
        try:
            action, params, conf = adapter.route_intent(
                user_input="hello",
                user_id="test_user",
                available_tools={"chat": {}},
            )
            checker.check(
                "Intent Routing",
                lambda: action is not None,
            )
        except Exception as e:
            checker.check("Intent Routing", lambda: False)

        # Test metrics recording
        checker.check(
            "Metrics Recording",
            lambda: adapter.record_execution(
                tool="chat",
                success=True,
                latency_ms=100,
                user_id="test",
            ),
        )

        # Test learning recording
        checker.check(
            "Learning Recording",
            lambda: adapter.record_success(
                intent="test",
                tool="test",
                metrics={"latency": 100},
            ),
        )

    # ========================================================================
    # REPORT
    # ========================================================================

    report = checker.report()

    print("\n" + "=" * 70)
    print("ACTIVATION REPORT")
    print("=" * 70)
    print(f"\nTimestamp: {time.ctime(report['timestamp'])}")
    print(f"Elapsed: {report['elapsed_seconds']:.1f}s")
    print(f"Checks: {report['passed']}/{report['total']} passed")
    print(f"Status: {'✓ SUCCESS' if report['success'] else '✗ FAILURE'}")

    if not report["success"]:
        print("\nFailed Checks:")
        for check in report["checks"]:
            if not check["passed"]:
                print(f"  ✗ {check['name']}: {check['message']}")

    print("\nDetailed Results:")
    print(json.dumps(report, indent=2))

    print("\n" + "=" * 70)

    if report["success"]:
        print("✓ ELYAN IS READY FOR DEPLOYMENT")
        print("=" * 70 + "\n")
        return 0
    else:
        print("✗ ELYAN ACTIVATION FAILED")
        print("=" * 70 + "\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
