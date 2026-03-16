#!/usr/bin/env python3
"""
Analyze Intent Patterns

Analyze what patterns Elyan has learned, common misunderstandings,
and recommendations for improvement.

Usage:
    python scripts/analyze_intent_patterns.py [--user USER_ID] [--export]
"""

import sys
import argparse
import json
from pathlib import Path
from collections import defaultdict
from core.intent import UserIntentMemory, FastMatcher, IntentMetricsTracker
from utils.logger import get_logger

logger = get_logger("analyze_intent_patterns")


class PatternAnalyzer:
    """Analyze learned intent patterns."""

    def __init__(self):
        self.memory = UserIntentMemory()
        self.matcher = FastMatcher()
        self.metrics = IntentMetricsTracker()

    def analyze(self, user_id: str = None, export: bool = False) -> None:
        """Analyze patterns."""
        print("\n" + "=" * 70)
        print("INTENT PATTERN ANALYSIS")
        print("=" * 70)

        if user_id:
            self._analyze_user_patterns(user_id)
        else:
            self._analyze_global_patterns()

        self._analyze_tier1_patterns()

        if export:
            self._export_analysis()

    def _analyze_user_patterns(self, user_id: str) -> None:
        """Analyze patterns for specific user."""
        print(f"\n--- USER PATTERNS: {user_id} ---")

        patterns = self.memory.export_patterns(user_id)
        if not patterns:
            print(f"No patterns found for user {user_id}")
            return

        print(f"\nTotal patterns: {len(patterns)}")

        # Group by action
        by_action = defaultdict(list)
        for pattern in patterns:
            by_action[pattern["action"]].append(pattern)

        print(f"Unique actions: {len(by_action)}")

        print("\nPatterns by action:")
        for action, action_patterns in sorted(
            by_action.items(),
            key=lambda x: len(x[1]),
            reverse=True
        ):
            total_freq = sum(p["frequency"] for p in action_patterns)
            avg_conf = sum(p["confidence"] for p in action_patterns) / len(action_patterns)
            print(f"\n  {action}:")
            print(f"    Patterns: {len(action_patterns)}")
            print(f"    Total frequency: {total_freq}")
            print(f"    Avg confidence: {avg_conf:.2f}")

            # Show top patterns
            sorted_patterns = sorted(
                action_patterns,
                key=lambda p: p["frequency"],
                reverse=True
            )
            for pattern in sorted_patterns[:3]:
                print(f"      • '{pattern['input']}' (freq: {pattern['frequency']})")

        # Find low-confidence patterns
        low_conf = [p for p in patterns if p["confidence"] < 0.70]
        if low_conf:
            print(f"\n⚠ Low confidence patterns ({len(low_conf)}):")
            for pattern in low_conf[:5]:
                print(f"  • '{pattern['input']}' → {pattern['action']} ({pattern['confidence']:.2f})")

    def _analyze_global_patterns(self) -> None:
        """Analyze all patterns globally."""
        print("\n--- GLOBAL PATTERN STATISTICS ---")

        stats = self.memory.get_stats()
        print(f"\nTotal users: {stats.get('users', 0)}")
        print(f"Total patterns: {stats.get('total_patterns', 0)}")
        print(f"Unique actions: {stats.get('unique_actions', 0)}")

    def _analyze_tier1_patterns(self) -> None:
        """Analyze Tier 1 pattern distribution."""
        print("\n--- TIER 1 FAST MATCH PATTERNS ---")

        pattern_count = self.matcher.get_pattern_count()
        print(f"\nTotal Tier 1 patterns: {pattern_count}")

        # Group by tool
        by_tool = defaultdict(list)
        for db_key, entry in self.matcher.db.items():
            tool = entry["tool"]
            patterns = entry.get("patterns", [])
            by_tool[tool].append((db_key, patterns))

        print(f"Unique tools: {len(by_tool)}")

        print("\nTier 1 coverage by tool:")
        for tool, entries in sorted(
            by_tool.items(),
            key=lambda x: sum(len(patterns) for _, patterns in x[1]),
            reverse=True
        ):
            total_patterns = sum(len(patterns) for _, patterns in entries)
            print(f"  {tool}: {total_patterns} patterns")

        # Find underutilized patterns
        underutilized = []
        for db_key, entry in self.matcher.db.items():
            if len(entry.get("patterns", [])) == 1:
                underutilized.append((db_key, entry))

        if underutilized:
            print(f"\n⚠ Underutilized patterns ({len(underutilized)}):")
            for db_key, entry in underutilized[:10]:
                patterns = entry.get("patterns", [])
                print(f"  • {db_key}: {patterns}")

    def _export_analysis(self) -> None:
        """Export analysis to file."""
        export_dir = Path("artifacts/intent_analysis")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Export tier 1 patterns
        tier1_data = {
            "total_patterns": self.matcher.get_pattern_count(),
            "db_entries": {}
        }

        for db_key, entry in self.matcher.db.items():
            tier1_data["db_entries"][db_key] = {
                "tool": entry["tool"],
                "pattern_count": len(entry.get("patterns", [])),
                "patterns": entry.get("patterns", [])
            }

        with open(export_dir / "tier1_patterns.json", "w", encoding="utf-8") as f:
            json.dump(tier1_data, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Exported analysis to {export_dir}")


def recommend_improvements() -> None:
    """Print improvement recommendations."""
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS FOR IMPROVEMENT")
    print("=" * 70)

    recommendations = [
        {
            "title": "Expand Tier 1 patterns",
            "description": "Add 20+ more exact/fuzzy patterns for common user inputs",
            "benefit": "Reduce latency and improve coverage"
        },
        {
            "title": "Add multilingual support",
            "description": "Learn patterns in Turkish, English, and mixed languages",
            "benefit": "Better user experience for multilingual users"
        },
        {
            "title": "Implement context awareness",
            "description": "Use conversation history to disambiguate intent",
            "benefit": "Higher accuracy for ambiguous inputs"
        },
        {
            "title": "Add feedback loop",
            "description": "User can correct misidentified intents on the fly",
            "benefit": "Continuous improvement from real usage"
        },
        {
            "title": "Implement analytics dashboard",
            "description": "Real-time view of intent distribution and accuracy",
            "benefit": "Better monitoring and optimization"
        }
    ]

    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec['title']}")
        print(f"   {rec['description']}")
        print(f"   → {rec['benefit']}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze Intent Patterns"
    )
    parser.add_argument("--user", help="Analyze specific user")
    parser.add_argument("--export", action="store_true", help="Export analysis to files")

    args = parser.parse_args()

    analyzer = PatternAnalyzer()
    analyzer.analyze(user_id=args.user, export=args.export)
    recommend_improvements()


if __name__ == "__main__":
    main()
