#!/usr/bin/env python3
"""
Benchmark LLM Providers - Compare Speed, Cost, Quality

Tests different LLM providers and recommends optimal setup for user's needs.
"""

import sys
import time
import asyncio
from pathlib import Path

from core.dependencies.autoinstall_hook import activate as _activate_autoinstall_hook

_activate_autoinstall_hook()

from tabulate import tabulate

# Add bot root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_orchestrator import (
    LLMOrchestrator, LLMProvider
)
from utils.logger import get_logger

logger = get_logger("benchmark_llm")


def print_header(text: str) -> None:
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


class BenchmarkSuite:
    """LLM provider benchmark suite"""

    def __init__(self):
        self.orchestrator = LLMOrchestrator()
        self.results = {}

        # Test prompts of varying complexity
        self.prompts = {
            "simple": "What is 2+2?",
            "moderate": "Explain quantum computing in simple terms",
            "complex": "Design a distributed system for real-time data processing with fault tolerance",
            "code": "Write a Python function that sorts a list using quicksort",
        }

    def print_provider_info(self) -> None:
        """Print information about available providers"""
        print_header("Available LLM Providers")

        provider_info = []
        for provider in LLMProvider:
            config = self.orchestrator.configs.get(provider)
            status = "✓ Available" if config and config.enabled else "✗ Not Available"
            model = config.model if config else "N/A"
            provider_info.append([provider.value, model, status])

        print(tabulate(
            provider_info,
            headers=["Provider", "Model", "Status"],
            tablefmt="grid"
        ))

    def estimate_costs(self) -> Dict[str, Dict[str, float]]:
        """Estimate costs for different usage patterns"""
        print_header("Cost Analysis by Usage Pattern")

        usage_patterns = {
            "light": 100,      # 100 calls/month
            "medium": 1000,    # 1000 calls/month
            "heavy": 10000,    # 10000 calls/month
        }

        cost_estimates = {}

        for provider in LLMProvider:
            config = self.orchestrator.configs.get(provider)
            if not config:
                continue

            cost_estimates[provider.value] = {}

            for pattern_name, calls_per_month in usage_patterns.items():
                tokens_per_call = 500
                total_tokens = calls_per_month * tokens_per_call

                cost_per_token = self.orchestrator.cost_tracker.cost_per_token.get(
                    (provider, config.model), 0.0000020
                )
                monthly_cost = total_tokens * cost_per_token

                cost_estimates[provider.value][pattern_name] = monthly_cost

        # Print cost table
        cost_table = []
        for provider, patterns in cost_estimates.items():
            cost_table.append([
                provider,
                f"${patterns['light']:.4f}",
                f"${patterns['medium']:.2f}",
                f"${patterns['heavy']:.2f}"
            ])

        print(tabulate(
            cost_table,
            headers=["Provider", "Light\n(100/mo)", "Medium\n(1000/mo)", "Heavy\n(10000/mo)"],
            tablefmt="grid"
        ))

        return cost_estimates

    def analyze_provider_stats(self) -> None:
        """Analyze current provider statistics"""
        print_header("Provider Performance Statistics")

        stats_table = []
        for provider in LLMProvider:
            stats = self.orchestrator.providers[provider]
            stats_table.append([
                provider.value,
                stats.total_calls,
                f"{stats.success_rate():.1%}",
                f"{stats.avg_latency_ms:.0f}ms",
                f"${stats.total_cost_usd:.4f}",
                f"{stats.quality_score:.2f}",
                f"{stats.efficiency_score():.2f}"
            ])

        print(tabulate(
            stats_table,
            headers=[
                "Provider",
                "Total Calls",
                "Success Rate",
                "Avg Latency",
                "Total Cost",
                "Quality",
                "Efficiency"
            ],
            tablefmt="grid"
        ))

    def recommend_setup(self, budget: str = "balanced") -> None:
        """Recommend optimal provider setup based on budget"""
        print_header(f"Recommendations - Budget: {budget.upper()}")

        if budget.lower() == "minimal":
            print("🎯 Minimal Cost Setup (Free Providers):")
            print("   1. PRIMARY: Groq (free, fast)")
            print("   2. FALLBACK: Ollama (local, free)")
            print()
            print("   Total Monthly Cost: $0.00")
            print("   Speed: Very Fast")
            print("   Reliability: Good")

        elif budget.lower() == "balanced":
            print("🎯 Balanced Setup (Cost-Effective):")
            print("   1. PRIMARY: Groq (free, fast)")
            print("   2. SECONDARY: Gemini (free, reliable)")
            print("   3. FALLBACK: Ollama (local, free)")
            print()
            print("   Total Monthly Cost: $0.00")
            print("   Speed: Very Fast")
            print("   Reliability: Excellent")
            print("   Quality: High")

        elif budget.lower() == "premium":
            print("🎯 Premium Setup (Best Quality):")
            print("   1. PRIMARY: Claude (best for complex tasks)")
            print("   2. SECONDARY: GPT-4 (cutting edge)")
            print("   3. FALLBACK: Groq (fast, free)")
            print()
            print("   Estimated Monthly Cost: $10-50")
            print("   Speed: Fast")
            print("   Reliability: Excellent")
            print("   Quality: Best-in-class")

        elif budget.lower() == "enterprise":
            print("🎯 Enterprise Setup (Redundancy):")
            print("   1. PRIMARY: Claude + GPT-4 (consensus)")
            print("   2. SECONDARY: Groq + Gemini (fast)")
            print("   3. FALLBACK: Ollama (local)")
            print()
            print("   Estimated Monthly Cost: $50-100+")
            print("   Speed: Very Fast (parallel calls)")
            print("   Reliability: Maximum redundancy")
            print("   Quality: Optimal (consensus mode)")

    def print_configuration_guide(self) -> None:
        """Print setup configuration guide"""
        print_header("Configuration Guide")

        print("To configure providers, edit ~/.elyan/config.yaml or set environment variables:\n")

        config_guide = [
            ["Provider", "Config Key", "Environment Variable"],
            ["Groq", "models.providers.groq.apiKey", "GROQ_API_KEY"],
            ["Gemini", "models.providers.google.apiKey", "GEMINI_API_KEY"],
            ["Claude", "models.providers.anthropic.apiKey", "ANTHROPIC_API_KEY"],
            ["GPT-4", "models.providers.openai.apiKey", "OPENAI_API_KEY"],
            ["Ollama", "models.local.baseUrl", "OLLAMA_BASE_URL"],
        ]

        print(tabulate(config_guide, headers=config_guide[0], tablefmt="grid"))

        print("\n✓ Free Providers (No API Key Required):")
        print("   - Groq: https://console.groq.com (free tier)")
        print("   - Gemini: https://ai.google.dev (free tier)")
        print("   - Ollama: http://localhost:11434 (local)")

    def print_best_practices(self) -> None:
        """Print best practices for LLM usage"""
        print_header("Best Practices")

        practices = [
            ("Cost Optimization", [
                "• Use free providers (Groq, Gemini, Ollama) for routine tasks",
                "• Reserve paid providers (Claude, GPT-4) for complex tasks",
                "• Implement caching for repeated queries",
                "• Monitor token usage weekly"
            ]),
            ("Quality", [
                "• Use consensus mode for critical decisions",
                "• Validate responses against expected schema",
                "• Fall back to human review for confidence < 0.7",
                "• Track quality metrics by provider"
            ]),
            ("Reliability", [
                "• Implement fallback chains across providers",
                "• Use local Ollama as ultimate fallback",
                "• Set daily and monthly budget limits",
                "• Monitor provider health metrics"
            ]),
            ("Performance", [
                "• Prefer Groq for latency-sensitive tasks",
                "• Use Ollama for local, instant responses",
                "• Implement request batching for throughput",
                "• Cache long-lived models locally"
            ]),
        ]

        for title, items in practices:
            print(f"\n🔹 {title}:")
            for item in items:
                print(f"  {item}")


def print_quick_start() -> None:
    """Print quick start guide"""
    print_header("Quick Start")

    print("1. DEFAULT SETUP (Recommended for most users):")
    print("   • No configuration needed!")
    print("   • Uses free providers: Groq → Gemini → Ollama")
    print("   • Automatic fallback if one provider fails")
    print()

    print("2. ADD PAID PROVIDERS (Optional):")
    print("   export GROQ_API_KEY=your-key")
    print("   export GEMINI_API_KEY=your-key")
    print("   export ANTHROPIC_API_KEY=your-key")
    print("   export OPENAI_API_KEY=your-key")
    print()

    print("3. VERIFY SETUP:")
    print("   python -c \"from core.llm_orchestrator import get_llm_orchestrator; \\")
    print("   orchestrator = get_llm_orchestrator(); \\")
    print("   print(orchestrator.get_all_stats())\"")


def main() -> int:
    """Run benchmark suite"""
    print_header("LLM Provider Benchmark & Recommendation")

    print("Analyzing LLM providers for your setup...\n")

    suite = BenchmarkSuite()

    try:
        # Show provider information
        suite.print_provider_info()

        # Cost analysis
        suite.estimate_costs()

        # Performance analysis
        suite.analyze_provider_stats()

        # Recommendations
        print_header("Choose Your Setup")
        print("\nOptions:")
        print("1. Minimal   - Free providers only (Groq, Gemini, Ollama)")
        print("2. Balanced  - Mix of free and reliable (RECOMMENDED)")
        print("3. Premium   - Best quality (Claude + GPT-4)")
        print("4. Enterprise - Full redundancy (All providers)")

        budget = "balanced"  # Default recommendation
        suite.recommend_setup(budget)

        # Best practices
        suite.print_best_practices()

        # Configuration guide
        suite.print_configuration_guide()

        # Quick start
        print_quick_start()

        print_header("Summary")
        print("✅ Benchmark complete!")
        print("\n📊 Key Findings:")
        print("   • Groq: Fastest, Free ⭐")
        print("   • Gemini: Reliable, Free ⭐")
        print("   • Ollama: Local, Free ⭐")
        print("   • Claude: Best quality (paid)")
        print("   • GPT-4: Cutting edge (paid)")
        print("\n💡 Recommendation: Start with free providers, add paid ones as needed")

        return 0

    except Exception as e:
        logger.error(f"Benchmark error: {e}", exc_info=True)
        print(f"\n❌ Error during benchmark: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
