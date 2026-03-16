#!/usr/bin/env python3
"""
NLU System Verification and Integration Tests

Comprehensive verification that all NLU components work correctly.
Tests integration with the rest of the system.

Usage:
    python scripts/verify_nlu_system.py [--full] [--verbose]
"""

import sys
import time
import json
from pathlib import Path

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


class NLUVerification:
    """Comprehensive NLU system verification."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_skipped = 0

    def run(self, full: bool = False) -> int:
        """Run verification suite."""
        print("\n" + "=" * 70)
        print(f"{BOLD}NLU SYSTEM VERIFICATION{RESET}")
        print("=" * 70)

        print(f"\n{BOLD}1. Module Import Tests{RESET}")
        self._test_imports()

        print(f"\n{BOLD}2. Model Initialization Tests{RESET}")
        self._test_initialization()

        print(f"\n{BOLD}3. Tier 1 Functionality Tests{RESET}")
        self._test_tier1()

        print(f"\n{BOLD}4. Turkish NLP Tests{RESET}")
        self._test_turkish_nlp()

        print(f"\n{BOLD}5. User Memory Tests{RESET}")
        self._test_user_memory()

        print(f"\n{BOLD}6. Integration Tests{RESET}")
        self._test_integration()

        if full:
            print(f"\n{BOLD}7. Performance Tests{RESET}")
            self._test_performance()

        print(f"\n{BOLD}8. Summary{RESET}")
        self._print_summary()

        return 0 if self.tests_failed == 0 else 1

    def _test_imports(self) -> None:
        """Test all imports."""
        imports = [
            ("core.intent", "IntentResult"),
            ("core.intent", "IntentCandidate"),
            ("core.intent", "FastMatcher"),
            ("core.intent", "SemanticClassifier"),
            ("core.intent", "DeepReasoner"),
            ("core.intent", "UserIntentMemory"),
            ("core.intent", "MultiTaskDecomposer"),
            ("core.intent", "IntentDisambiguator"),
            ("core.intent", "IntentMetricsTracker"),
            ("core.turkish_nlp", "TurkishNLPAnalyzer"),
        ]

        for module, item in imports:
            try:
                exec(f"from {module} import {item}")
                self._pass(f"Import {module}.{item}")
            except Exception as e:
                self._fail(f"Import {module}.{item}: {e}")

    def _test_initialization(self) -> None:
        """Test component initialization."""
        try:
            from core.intent import FastMatcher
            matcher = FastMatcher()
            self._pass("FastMatcher initialization")

            if matcher.get_pattern_count() > 40:
                self._pass(f"Tier 1 patterns loaded ({matcher.get_pattern_count()})")
            else:
                self._fail(f"Insufficient Tier 1 patterns: {matcher.get_pattern_count()}")

        except Exception as e:
            self._fail(f"FastMatcher initialization: {e}")

        try:
            from core.intent import UserIntentMemory
            memory = UserIntentMemory()
            self._pass("UserIntentMemory initialization")
        except Exception as e:
            self._fail(f"UserIntentMemory initialization: {e}")

        try:
            from core.intent import IntentMetricsTracker
            metrics = IntentMetricsTracker()
            self._pass("IntentMetricsTracker initialization")
        except Exception as e:
            self._fail(f"IntentMetricsTracker initialization: {e}")

    def _test_tier1(self) -> None:
        """Test Tier 1 fast matching."""
        try:
            from core.intent import FastMatcher

            matcher = FastMatcher()

            test_cases = [
                ("screenshot", "take_screenshot"),
                ("merhaba", "chat"),
                ("sesi kapat", "set_volume"),
                ("ses aç", "set_volume"),
                ("mute", "set_volume"),
            ]

            for user_input, expected_action in test_cases:
                result = matcher.match(user_input)
                if result and result.action == expected_action:
                    self._pass(f"Tier 1: '{user_input}' → {expected_action}")
                else:
                    actual = result.action if result else "None"
                    self._fail(f"Tier 1: '{user_input}' expected {expected_action}, got {actual}")

        except Exception as e:
            self._fail(f"Tier 1 tests: {e}")

    def _test_turkish_nlp(self) -> None:
        """Test Turkish NLP functions."""
        try:
            from core.turkish_nlp import TurkishNLPAnalyzer

            # Test morpheme analysis
            analysis = TurkishNLPAnalyzer.analyze_morpheme("evde")
            if analysis["case"] == "locative" and analysis["stem"] == "ev":
                self._pass("Turkish morpheme analysis")
            else:
                self._fail(f"Turkish morpheme analysis: {analysis}")

            # Test number parsing
            num = TurkishNLPAnalyzer.parse_turkish_number("elli beş")
            if num == 55:
                self._pass("Turkish number parsing")
            else:
                self._fail(f"Turkish number parsing: expected 55, got {num}")

            # Test normalization
            text = TurkishNLPAnalyzer.normalize_turkish_text("  MERHABA???  ")
            if text == "merhaba":
                self._pass("Turkish text normalization")
            else:
                self._fail(f"Turkish text normalization: {text}")

        except Exception as e:
            self._fail(f"Turkish NLP tests: {e}")

    def _test_user_memory(self) -> None:
        """Test user memory system."""
        try:
            import tempfile
            from core.intent import UserIntentMemory

            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = f"{tmpdir}/test_memory.db"
                memory = UserIntentMemory(db_path=db_path)

                # Test learning
                memory.learn_pattern("user1", "screenshot", "take_screenshot", {})
                self._pass("User memory: learn pattern")

                # Test retrieval
                candidate = memory.get_intent("screenshot", "user1")
                if candidate and candidate.action == "take_screenshot":
                    self._pass("User memory: retrieve pattern")
                else:
                    self._fail("User memory: retrieve pattern")

                # Test stats
                stats = memory.get_stats()
                if stats.get("total_patterns", 0) > 0:
                    self._pass("User memory: statistics")
                else:
                    self._fail("User memory: statistics")

        except Exception as e:
            self._fail(f"User memory tests: {e}")

    def _test_integration(self) -> None:
        """Test integration between components."""
        try:
            from core.intent import (
                IntentResult, ConversationContext, TaskDefinition,
                DependencyGraph, IntentCandidate
            )

            # Test IntentResult
            result = IntentResult(
                user_input="screenshot",
                user_id="user1",
                action="take_screenshot",
                confidence=0.95
            )
            d = result.to_dict()
            if d["action"] == "take_screenshot":
                self._pass("IntentResult serialization")
            else:
                self._fail("IntentResult serialization")

            # Test ConversationContext
            context = ConversationContext(user_id="user1")
            context.add_message("user", "hello")
            if len(context.message_history) == 1:
                self._pass("ConversationContext")
            else:
                self._fail("ConversationContext")

            # Test TaskDefinition
            task = TaskDefinition(
                task_id="t1",
                action="take_screenshot",
                params={}
            )
            valid, error = task.validate({"take_screenshot"})
            if valid:
                self._pass("TaskDefinition validation")
            else:
                self._fail("TaskDefinition validation")

            # Test DependencyGraph
            graph = DependencyGraph(tasks=[task])
            if graph.is_valid():
                self._pass("DependencyGraph validation")
            else:
                self._fail("DependencyGraph validation")

        except Exception as e:
            self._fail(f"Integration tests: {e}")

    def _test_performance(self) -> None:
        """Test performance metrics."""
        try:
            from core.intent import FastMatcher, IntentMetricsTracker
            import statistics

            matcher = FastMatcher()
            metrics = IntentMetricsTracker()

            # Benchmark Tier 1
            latencies = []
            for _ in range(100):
                start = time.perf_counter()
                matcher.match("screenshot")
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)

            avg_latency = statistics.mean(latencies)
            if avg_latency < 1.0:
                self._pass(f"Tier 1 latency: {avg_latency:.2f}ms (excellent)")
            elif avg_latency < 2.0:
                self._pass(f"Tier 1 latency: {avg_latency:.2f}ms (good)")
            else:
                self._fail(f"Tier 1 latency: {avg_latency:.2f}ms (slow)")

        except Exception as e:
            self._fail(f"Performance tests: {e}")

    def _print_summary(self) -> None:
        """Print test summary."""
        total = self.tests_passed + self.tests_failed + self.tests_skipped

        print(f"\n{'-' * 70}")
        print(f"Passed:  {GREEN}{self.tests_passed}/{total}{RESET}")
        print(f"Failed:  {RED}{self.tests_failed}/{total}{RESET}")
        print(f"Skipped: {YELLOW}{self.tests_skipped}/{total}{RESET}")

        if self.tests_failed == 0:
            print(f"\n{GREEN}{BOLD}✓ All tests passed!{RESET}")
            print(f"\nNLU System is ready for production integration.")
        else:
            print(f"\n{RED}{BOLD}✗ Some tests failed!{RESET}")
            print(f"\nPlease fix the issues above before production deployment.")

    def _pass(self, test_name: str) -> None:
        """Record passing test."""
        self.tests_passed += 1
        print(f"  {GREEN}✓{RESET} {test_name}")

    def _fail(self, test_name: str) -> None:
        """Record failing test."""
        self.tests_failed += 1
        print(f"  {RED}✗{RESET} {test_name}")

    def _skip(self, test_name: str) -> None:
        """Record skipped test."""
        self.tests_skipped += 1
        print(f"  {YELLOW}⊘{RESET} {test_name}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="NLU System Verification"
    )
    parser.add_argument("--full", action="store_true", help="Run full verification including performance")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    verifier = NLUVerification(verbose=args.verbose)
    return verifier.run(full=args.full)


if __name__ == "__main__":
    sys.exit(main())
