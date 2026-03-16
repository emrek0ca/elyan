#!/usr/bin/env python3
"""
Analyze Learning Progress - Show What Elyan Learned

Generates detailed report of learning progress, weak areas,
and personalized training recommendations.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add bot root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.training_system import get_training_system
from core.analytics_engine import get_analytics_engine
from utils.logger import get_logger

logger = get_logger("analyze_learning")


def print_header(text: str) -> None:
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def analyze_training_progress() -> None:
    """Analyze training system progress"""
    print_header("Training Progress Analysis")

    training = get_training_system()
    metrics = training.get_learning_metrics()

    print("📚 Learning Level Progression:")
    print(f"   Current Level: {metrics['learning_level']}")
    print(f"   Levels: Beginner → Intermediate → Advanced → Expert")
    print()

    print("📖 Patterns Learned:")
    print(f"   Total Patterns: {metrics['total_patterns']}")
    print(f"   Average Confidence: {metrics['avg_confidence']}")
    print(f"   Average Success Rate: {metrics['avg_success_rate']}")
    print()

    print("🎓 Knowledge Base:")
    if training.knowledge_base:
        total_uses = sum(e.times_used for e in training.knowledge_base.values())
        avg_uses = total_uses / len(training.knowledge_base)
        print(f"   Total Uses: {total_uses}")
        print(f"   Avg Uses per Pattern: {avg_uses:.1f}")

        # Top patterns
        sorted_patterns = sorted(
            training.knowledge_base.items(),
            key=lambda x: x[1].times_used,
            reverse=True
        )
        if sorted_patterns:
            print(f"\n   Top 5 Patterns:")
            for i, (pattern, entry) in enumerate(sorted_patterns[:5], 1):
                print(f"   {i}. {pattern[:30]}")
                print(f"      Confidence: {entry.confidence:.0%}, Uses: {entry.times_used}")
    else:
        print("   No patterns learned yet")
    print()

    print("🏆 Progress Milestones:")
    for name, milestone in training.progress_tracking.milestones.items():
        status = "✓" if milestone.achieved else "✗"
        achieved_date = milestone.achievement_date.strftime("%Y-%m-%d") if milestone.achieved else "N/A"
        print(f"   {status} {name}: {achieved_date}")


def analyze_reward_system() -> None:
    """Analyze reward system activity"""
    print_header("Reward System Analysis")

    training = get_training_system()
    reward_sys = training.reward_system

    print("🎯 Reward History:")
    print(f"   Total Rewards: {reward_sys.total_rewards:.1f}")
    print(f"   Reward Multiplier: {reward_sys.reward_multiplier:.1f}x")
    print()

    # Recent rewards
    recent_24h = reward_sys.get_recent_rewards(hours=24)
    recent_7d = reward_sys.get_recent_rewards(hours=168)

    print("📊 Recent Activity:")
    print(f"   Last 24 hours: {recent_24h:.1f} points")
    print(f"   Last 7 days: {recent_7d:.1f} points")
    print()

    # Reward analysis
    if reward_sys.reward_history:
        successes = sum(1 for _, _, r in reward_sys.reward_history if r > 0)
        failures = sum(1 for _, _, r in reward_sys.reward_history if r < 0)
        success_rate = successes / (successes + failures) if (successes + failures) > 0 else 0

        print("📈 Success Analysis:")
        print(f"   Successful Actions: {successes}")
        print(f"   Failed Actions: {failures}")
        print(f"   Success Rate: {success_rate:.1%}")


def analyze_concepts_learned() -> None:
    """Analyze learned concepts"""
    print_header("Concepts Learned")

    training = get_training_system()
    concepts = training.concept_progression.concepts

    print("🧠 Known Concepts:")
    high_confidence = []
    medium_confidence = []
    low_confidence = []

    for concept in concepts.values():
        if concept.confidence > 0.8:
            high_confidence.append(concept)
        elif concept.confidence > 0.6:
            medium_confidence.append(concept)
        else:
            low_confidence.append(concept)

    if high_confidence:
        print(f"\n   ⭐ High Confidence ({len(high_confidence)}):")
        for concept in high_confidence:
            print(f"      • {concept.name}: {concept.confidence:.0%}")
            print(f"        Definition: {concept.definition}")

    if medium_confidence:
        print(f"\n   ⭐ Medium Confidence ({len(medium_confidence)}):")
        for concept in medium_confidence:
            print(f"      • {concept.name}: {concept.confidence:.0%}")

    if low_confidence:
        print(f"\n   ⭐ Low Confidence ({len(low_confidence)}):")
        for concept in low_confidence:
            print(f"      • {concept.name}: {concept.confidence:.0%}")


def analyze_weak_areas() -> None:
    """Identify and report weak areas"""
    print_header("Weak Areas & Improvement Opportunities")

    training = get_training_system()
    metrics = training.get_learning_metrics()

    weak_areas = []

    # Check confidence
    if float(metrics['avg_confidence']) < 0.7:
        weak_areas.append(("Low Average Confidence", f"{metrics['avg_confidence']} (target: >0.8)"))

    # Check success rate
    if float(metrics['avg_success_rate'].rstrip('%')) < 80:
        weak_areas.append(("Low Success Rate", metrics['avg_success_rate']))

    # Check pattern coverage
    if int(metrics['total_patterns']) < 10:
        weak_areas.append(("Limited Pattern Coverage", f"{metrics['total_patterns']} patterns (target: >20)"))

    # Check reward score
    if float(metrics['reward_score']) < 5.0:
        weak_areas.append(("Low Reward Score", f"{metrics['reward_score']} (target: >10.0)"))

    if weak_areas:
        print("⚠️  Areas Needing Improvement:\n")
        for i, (area, current) in enumerate(weak_areas, 1):
            print(f"   {i}. {area}")
            print(f"      Current: {current}")
            print()
    else:
        print("✅ All metrics are within acceptable ranges!")

    print("\n💡 Recommendations:")
    if weak_areas:
        print("   1. Increase training examples (especially for low-confidence patterns)")
        print("   2. Provide more positive feedback for successful actions")
        print("   3. Record user corrections to improve from mistakes")
        print("   4. Focus on the most used patterns first")
    else:
        print("   1. Continue current training regimen")
        print("   2. Gradually increase complexity")
        print("   3. Explore new concept areas")
        print("   4. Practice edge cases")


def analyze_analytics() -> None:
    """Analyze analytics data"""
    print_header("Performance Analytics")

    analytics = get_analytics_engine()
    dashboard = analytics.get_dashboard_metrics()

    print("📊 Execution Metrics:")
    exec_metrics = dashboard.get("execution_metrics", {})
    print(f"   Total Executions: {exec_metrics.get('total_executions', 0)}")
    print(f"   Success Rate: {exec_metrics.get('success_rate', 'N/A')}")
    print(f"   Avg Latency: {exec_metrics.get('avg_latency_ms', 'N/A')}")
    print()

    print("🛠️  Tool Metrics:")
    tool_metrics = dashboard.get("tool_metrics", {})
    print(f"   Total Tools: {tool_metrics.get('total_tools', 0)}")
    print(f"   Avg Reliability: {tool_metrics.get('avg_reliability', 'N/A')}")
    print(f"   Top Tool: {tool_metrics.get('top_tool', 'N/A')}")
    print()

    print("👤 User Metrics:")
    user_metrics = dashboard.get("user_metrics", {})
    print(f"   Total Users: {user_metrics.get('total_users', 0)}")
    print(f"   Avg Learning Rate: {user_metrics.get('avg_learning_rate', 'N/A')}")
    print()

    print("🤖 LLM Metrics:")
    llm_metrics = dashboard.get("llm_metrics", {})
    print(f"   Providers Configured: {llm_metrics.get('total_providers', 0)}")
    print(f"   Avg Quality Score: {llm_metrics.get('avg_quality_score', 'N/A')}")
    print(f"   Total Cost: {llm_metrics.get('total_cost', 'N/A')}")


def generate_improvement_plan() -> None:
    """Generate personalized improvement plan"""
    print_header("Personalized Improvement Plan")

    training = get_training_system()
    metrics = training.get_learning_metrics()

    print("🎯 Phase 1: Foundation Building (Week 1)")
    print("   • Continue learning basic patterns")
    print("   • Aim for 20+ unique patterns")
    print("   • Target: 75%+ success rate")
    print()

    print("📈 Phase 2: Confidence Boost (Week 2)")
    print("   • Practice high-confidence patterns")
    print("   • Learn from mistakes (feedback)")
    print("   • Target: 85%+ success rate")
    print()

    print("🚀 Phase 3: Advanced Learning (Week 3)")
    if int(metrics['total_patterns']) > 20:
        print("   • Ready for fuzzy matching")
        print("   • Learn complex pattern combinations")
        print("   • Explore edge cases")
    else:
        print("   • Consolidate existing patterns first")
        print("   • Add more training examples")
    print()

    print("🎓 Phase 4: Mastery (Week 4)")
    print("   • Advance to ADVANCED learning level")
    print("   • Semantic understanding")
    print("   • Target: Expert level")
    print()

    print("✅ Suggested Actions Today:")
    print("   1. Add 5 new training examples")
    print("   2. Review weak areas from analysis above")
    print("   3. Set up weekly review schedule")


def export_report(output_file: str = None) -> None:
    """Export analysis as JSON report"""
    if not output_file:
        output_file = str(Path.home() / ".elyan" / "reports" / f"learning_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    training = get_training_system()
    analytics = get_analytics_engine()

    report = {
        "timestamp": datetime.now().isoformat(),
        "training": {
            "metrics": training.get_learning_metrics(),
            "learning_level": training.learning_level.name,
            "pattern_count": len(training.knowledge_base),
            "reward_total": training.reward_system.total_rewards,
        },
        "analytics": {
            "dashboard": analytics.get_dashboard_metrics(),
            "insights": analytics.generate_insights(),
        }
    }

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Report exported to: {output_file}")


def main() -> int:
    """Run analysis"""
    print_header("Elyan Learning Progress Analysis")

    try:
        analyze_training_progress()
        analyze_reward_system()
        analyze_concepts_learned()
        analyze_weak_areas()
        analyze_analytics()
        generate_improvement_plan()
        export_report()

        print_header("Analysis Complete")
        print("✅ Analysis finished successfully!")
        print("\n📂 Data Location:")
        print(f"   Training DB: ~/.elyan/training.db")
        print(f"   Analytics DB: ~/.elyan/analytics.db")

        return 0

    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        print(f"\n❌ Error during analysis: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
