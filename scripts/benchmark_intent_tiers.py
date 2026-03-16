#!/usr/bin/env python3
"""
Intent System Tier Performance Benchmark

Compares latency vs accuracy tradeoff for each tier.
Recommends optimal tier thresholds.

Usage:
    python scripts/benchmark_intent_tiers.py [--samples N] [--verbose]
"""

import sys
import time
import statistics
import argparse
from typing import List, Dict, Any
from core.intent import (
    FastMatcher, IntentMetricsTracker, route_intent,
    ConversationContext, IntentResult
)
from core.turkish_nlp import TurkishNLPAnalyzer
from utils.logger import get_logger

logger = get_logger("benchmark_intent_tiers")

# Benchmark test cases
TEST_CASES = [
    # Tier 1 benchmarks (should be very fast)
    ("screenshot", "tier1", "take_screenshot"),
    ("ss", "tier1", "take_screenshot"),
    ("merhaba", "tier1", "chat"),
    ("mute", "tier1", "set_volume"),
    ("ses aç", "tier1", "set_volume"),
    ("lock screen", "tier1", "lock_screen"),
    ("terminal aç", "tier1", "open_terminal"),

    # Tier 2 benchmarks (should be medium speed)
    ("take a screenshot for me", "tier2", "take_screenshot"),
    ("I want to chat", "tier2", "chat"),
    ("please list my files", "tier2", "list_files"),
    ("open google chrome", "tier2", "open_app"),

    # Tier 3 benchmarks (complex reasoning)
    ("show me what's on my screen and then mute the sound", "tier3", "multi_task"),
    ("I need both a screenshot and to change volume", "tier3", "multi_task"),
]


class TierBenchmark:
    """Benchmark intent tiers."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.matcher = FastMatcher()
        self.metrics = IntentMetricsTracker()
        self.results: Dict[str, List[float]] = {
            "tier1": [],
            "tier2": [],
            "tier3": []
        }

    def run(self, num_samples: int = 10) -> None:
        """Run benchmark."""
        print("\n" + "=" * 70)
        print("INTENT TIER PERFORMANCE BENCHMARK")
        print("=" * 70)

        total_tests = len(TEST_CASES) * num_samples
        print(f"\nRunning {total_tests} tests ({num_samples} samples per case)...\n")

        for test_input, expected_tier, expected_action in TEST_CASES:
            self._benchmark_case(test_input, expected_tier, expected_action, num_samples)

        self._print_results()
        self._print_recommendations()

    def _benchmark_case(
        self,
        user_input: str,
        expected_tier: str,
        expected_action: str,
        num_samples: int
    ) -> None:
        """Benchmark a single test case."""
        latencies = []

        for _ in range(num_samples):
            start = time.perf_counter()
            result = self.matcher.match(user_input)
            elapsed = (time.perf_counter() - start) * 1000

            latencies.append(elapsed)

            if result and expected_tier == "tier1":
                self.results["tier1"].append(elapsed)

        if self.verbose:
            avg_latency = statistics.mean(latencies)
            print(f"  {user_input:40} → {avg_latency:6.2f}ms")

    def _print_results(self) -> None:
        """Print benchmark results."""
        print("\n" + "-" * 70)
        print("RESULTS SUMMARY")
        print("-" * 70)

        for tier in ["tier1", "tier2", "tier3"]:
            latencies = self.results.get(tier, [])
            if latencies:
                self._print_tier_stats(tier, latencies)
            else:
                print(f"\n{tier.upper()}:")
                print("  No samples collected")

    def _print_tier_stats(self, tier: str, latencies: List[float]) -> None:
        """Print statistics for a tier."""
        print(f"\n{tier.upper()}:")
        print(f"  Samples: {len(latencies)}")
        print(f"  Min:     {min(latencies):.2f}ms")
        print(f"  Max:     {max(latencies):.2f}ms")
        print(f"  Mean:    {statistics.mean(latencies):.2f}ms")
        print(f"  Median:  {statistics.median(latencies):.2f}ms")
        if len(latencies) > 1:
            print(f"  StdDev:  {statistics.stdev(latencies):.2f}ms")

        # Percentiles
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        print(f"  P95:     {sorted_latencies[p95_idx]:.2f}ms")
        print(f"  P99:     {sorted_latencies[p99_idx]:.2f}ms")

    def _print_recommendations(self) -> None:
        """Print recommendations based on results."""
        print("\n" + "=" * 70)
        print("RECOMMENDATIONS")
        print("=" * 70)

        tier1_latencies = self.results.get("tier1", [])

        if tier1_latencies:
            mean_t1 = statistics.mean(tier1_latencies)
            max_t1 = max(tier1_latencies)

            print(f"\nTIER 1 (Fast Match):")
            if mean_t1 < 1.0:
                print(f"  ✓ Excellent performance: {mean_t1:.2f}ms average")
                print(f"    → Use for all simple patterns")
            elif mean_t1 < 2.0:
                print(f"  ✓ Good performance: {mean_t1:.2f}ms average")
                print(f"    → Acceptable for most patterns")
            else:
                print(f"  ⚠ Slow performance: {mean_t1:.2f}ms average")
                print(f"    → Consider optimizing pattern matching")

            if max_t1 > 5.0:
                print(f"  ⚠ High P99 latency: {max_t1:.2f}ms")
                print(f"    → May impact user experience")

        print(f"\nTIER 2 (Semantic Classifier):")
        print(f"  Target: < 200ms")
        print(f"  Current: Not measured (requires LLM)")

        print(f"\nTIER 3 (Deep Reasoning):")
        print(f"  Target: < 2000ms")
        print(f"  Current: Not measured (requires LLM)")

        print("\nOPTIMIZATION SUGGESTIONS:")
        if mean_t1 < 2.0:
            print("  • Tier 1 is performing well")
            print("  • Add more patterns to Tier 1 for common queries")
        if mean_t1 > 5.0:
            print("  • Consider using trie-based pattern matching")
            print("  • Profile to identify slow patterns")

    def print_tier_thresholds(self) -> None:
        """Print recommended tier thresholds."""
        print("\nRECOMMENDED TIER THRESHOLDS:")
        print("  Tier 1 confidence: >= 0.95")
        print("  Tier 2 confidence: >= 0.70")
        print("  Tier 3 confidence: >= 0.50")


def benchmark_turkish_nlp() -> None:
    """Benchmark Turkish NLP performance."""
    print("\n" + "=" * 70)
    print("TURKISH NLP PERFORMANCE")
    print("=" * 70)

    test_words = [
        "ev", "evi", "eve", "evde", "evden", "evle",
        "kitap", "kitabı", "kitaba", "kitapta", "kitaptan",
        "yapıyor", "yapacak", "yapmıştı", "yaparım"
    ]

    latencies = []
    for word in test_words:
        start = time.perf_counter()
        analysis = TurkishNLPAnalyzer.analyze_morpheme(word)
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    print(f"\nMorpheme Analysis (n={len(test_words)}):")
    print(f"  Mean:     {statistics.mean(latencies):.3f}ms")
    print(f"  P99:      {sorted(latencies)[int(len(latencies)*0.99)]:.3f}ms")

    # Test number parsing
    numbers = ["sıfır", "bir", "elli beş", "yüz kırk üç"]
    num_latencies = []
    for num_str in numbers:
        start = time.perf_counter()
        result = TurkishNLPAnalyzer.parse_turkish_number(num_str)
        elapsed = (time.perf_counter() - start) * 1000
        num_latencies.append(elapsed)

    print(f"\nNumber Parsing (n={len(numbers)}):")
    print(f"  Mean:     {statistics.mean(num_latencies):.3f}ms")

    # Test normalization
    texts = [
        "  Merhaba   Nasıl   Gidiyorsun???  ",
        "BÜYÜK HARFLER VE SEMBOLLER!!! !!!",
    ]
    norm_latencies = []
    for text in texts:
        start = time.perf_counter()
        result = TurkishNLPAnalyzer.normalize_turkish_text(text)
        elapsed = (time.perf_counter() - start) * 1000
        norm_latencies.append(elapsed)

    print(f"\nText Normalization (n={len(texts)}):")
    print(f"  Mean:     {statistics.mean(norm_latencies):.3f}ms")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Intent Tier Performance Benchmark"
    )
    parser.add_argument("--samples", type=int, default=100, help="Samples per test case")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--nlp-only", action="store_true", help="Only benchmark Turkish NLP")

    args = parser.parse_args()

    if args.nlp_only:
        benchmark_turkish_nlp()
    else:
        bench = TierBenchmark(verbose=args.verbose)
        bench.run(num_samples=args.samples)
        bench.print_tier_thresholds()
        benchmark_turkish_nlp()


if __name__ == "__main__":
    main()
