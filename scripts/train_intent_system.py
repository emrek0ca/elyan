#!/usr/bin/env python3
"""
Interactive Intent System Training Script

Teaches Elyan Bot to recognize new user patterns.
Shows learning progress and exports learned patterns.

Usage:
    python scripts/train_intent_system.py [--user USER_ID] [--action ACTION]
"""

import sys
import argparse
import json
from pathlib import Path
from core.intent import (
    UserIntentMemory, FastMatcher, IntentRouter, route_intent
)
from core.intent.intent_metrics import IntentMetricsTracker
from utils.logger import get_logger

logger = get_logger("train_intent_system")


class InteractiveTrainer:
    """Interactive trainer for intent system."""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.memory = UserIntentMemory()
        self.matcher = FastMatcher()
        self.metrics = IntentMetricsTracker()
        self.session_patterns = []

    def run(self) -> None:
        """Start interactive training session."""
        print("\n" + "=" * 60)
        print("ELYAN BOT - INTENT SYSTEM INTERACTIVE TRAINER")
        print("=" * 60)
        print(f"\nUser ID: {self.user_id}")
        print("\nCommands:")
        print("  'teach' - Teach a new pattern")
        print("  'test'  - Test pattern recognition")
        print("  'stats' - Show training statistics")
        print("  'export' - Export learned patterns")
        print("  'quit'  - Exit")
        print("-" * 60)

        while True:
            cmd = input("\n> ").strip().lower()

            if cmd == "quit" or cmd == "exit":
                self._save_session()
                print("\nTraining session ended. Goodbye!")
                break
            elif cmd == "teach":
                self._teach_pattern()
            elif cmd == "test":
                self._test_patterns()
            elif cmd == "stats":
                self._show_stats()
            elif cmd == "export":
                self._export_patterns()
            elif cmd == "help":
                self._show_help()
            else:
                print("Unknown command. Type 'help' for assistance.")

    def _teach_pattern(self) -> None:
        """Interactive pattern teaching."""
        print("\n--- TEACH NEW PATTERN ---")
        user_input = input("What the user might say: ").strip()
        if not user_input:
            print("Cancelled.")
            return

        action = input("What action should this trigger?: ").strip()
        if not action:
            print("Cancelled.")
            return

        params_str = input("Parameters (JSON, or press Enter for none): ").strip()
        params = {}
        if params_str:
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError:
                print("Invalid JSON. Using empty params.")

        # Learn pattern
        self.memory.learn_pattern(self.user_id, user_input, action, params)
        self.session_patterns.append({
            "input": user_input,
            "action": action,
            "params": params
        })

        print(f"✓ Learned: '{user_input}' → {action}")

        # Also add to Tier 1 if it's a common action
        if action in [
            "set_volume", "take_screenshot", "chat", "lock_screen",
            "open_app", "list_files", "send_notification"
        ]:
            self.matcher.add_pattern(action, user_input.lower())
            print(f"  Also added to Tier 1 Fast Match")

    def _test_patterns(self) -> None:
        """Test pattern recognition."""
        print("\n--- TEST PATTERNS ---")
        user_input = input("Enter test input: ").strip()
        if not user_input:
            return

        # Test Tier 1
        print("\nTier 1 (Fast Match):")
        t1_result = self.matcher.match(user_input)
        if t1_result:
            print(f"  ✓ {t1_result.action} ({t1_result.confidence:.0%})")
        else:
            print("  × No match")

        # Test User Memory
        print("\nUser Memory:")
        mem_result = self.memory.get_intent(user_input, self.user_id)
        if mem_result:
            print(f"  ✓ {mem_result.action} ({mem_result.confidence:.0%})")
        else:
            print("  × No match")

    def _show_stats(self) -> None:
        """Show training statistics."""
        print("\n--- TRAINING STATISTICS ---")

        # Memory stats
        mem_stats = self.memory.get_stats()
        print(f"\nUser Memory:")
        print(f"  Total users: {mem_stats.get('users', 0)}")
        print(f"  Total patterns: {mem_stats.get('total_patterns', 0)}")
        print(f"  Unique actions: {mem_stats.get('unique_actions', 0)}")

        # User's top intents
        top_intents = self.memory.get_top_intents(self.user_id, limit=5)
        if top_intents:
            print(f"\nTop intents for {self.user_id}:")
            for intent in top_intents:
                print(f"  - {intent['action']}: {intent['frequency']} times "
                      f"({intent['confidence']:.0%} confidence)")

        # Tier 1 stats
        print(f"\nTier 1 Fast Match:")
        print(f"  Total patterns: {self.matcher.get_pattern_count()}")

        # Session stats
        print(f"\nThis session:")
        print(f"  Patterns taught: {len(self.session_patterns)}")

    def _export_patterns(self) -> None:
        """Export learned patterns to JSON."""
        print("\n--- EXPORT PATTERNS ---")

        patterns = self.memory.export_patterns(self.user_id)
        if not patterns:
            print(f"No patterns found for user {self.user_id}")
            return

        # Export to file
        export_dir = Path("artifacts/intent_training")
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = export_dir / f"patterns_{self.user_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)

        print(f"✓ Exported {len(patterns)} patterns to {filename}")

        # Show summary
        print(f"\nPattern Summary:")
        for pattern in patterns[:5]:
            print(f"  '{pattern['input']}' → {pattern['action']}")
        if len(patterns) > 5:
            print(f"  ... and {len(patterns) - 5} more")

    def _save_session(self) -> None:
        """Save session results."""
        if self.session_patterns:
            print(f"\nSaved {len(self.session_patterns)} patterns this session.")

    def _show_help(self) -> None:
        """Show help message."""
        print("""
COMMANDS:
  teach   - Teach a new pattern (user input → action mapping)
  test    - Test if input is recognized
  stats   - Show training statistics
  export  - Export patterns to JSON file
  quit    - Exit training session

EXAMPLES:
  User input: "take a screenshot"
  Action: take_screenshot

  User input: "mute sound"
  Action: set_volume
  Parameters: {"volume": 0}
        """)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive Intent System Training"
    )
    parser.add_argument("--user", default="default", help="User ID")
    parser.add_argument("--action", help="Specific action to train")
    parser.add_argument("--batch", help="Batch training file (JSON)")

    args = parser.parse_args()

    trainer = InteractiveTrainer(user_id=args.user)

    if args.batch:
        # Batch training from file
        print(f"Loading batch training file: {args.batch}")
        try:
            with open(args.batch, "r", encoding="utf-8") as f:
                patterns = json.load(f)

            for pattern in patterns:
                trainer.memory.learn_pattern(
                    args.user,
                    pattern["input"],
                    pattern["action"],
                    pattern.get("params", {})
                )
            print(f"✓ Trained {len(patterns)} patterns")
        except Exception as e:
            print(f"Error loading batch file: {e}")
            sys.exit(1)
    else:
        # Interactive training
        trainer.run()


if __name__ == "__main__":
    main()
