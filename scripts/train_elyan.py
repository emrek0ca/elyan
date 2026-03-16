#!/usr/bin/env python3
"""
Train Elyan - Interactive teaching loop

Demonstrates how Elyan learns progressively through examples,
rewards, and feedback. Shows the child-learning model in action.
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# Add bot root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.training_system import (
    ChildLearningModel, TrainingExample, LearningLevel
)
from utils.logger import get_logger

logger = get_logger("train_elyan")


def print_header(text: str) -> None:
    """Print formatted header"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_progress(training_system: ChildLearningModel) -> None:
    """Print current training progress"""
    metrics = training_system.get_learning_metrics()
    print(f"📊 Learning Progress:")
    print(f"   Level: {metrics['learning_level']}")
    print(f"   Patterns: {metrics['total_patterns']}")
    print(f"   Confidence: {metrics['avg_confidence']}")
    print(f"   Success Rate: {metrics['avg_success_rate']}")
    print(f"   Reward Score: {metrics['reward_score']}")
    print(f"   Overall Progress: {metrics['progress']}\n")


class TrainingSession:
    """Interactive training session"""

    def __init__(self):
        self.training_system = ChildLearningModel()
        self.session_start = datetime.now()
        self.examples_learned = 0
        self.corrections_made = 0

    def teach_greeting_concepts(self) -> None:
        """Teach greeting recognition"""
        print_header("STAGE 1: Teaching Greeting Concepts")

        examples = [
            ("hello", "greeting", "Recognized greeting", True),
            ("hi there", "greeting", "Friendly greeting", True),
            ("merhaba", "greeting", "Turkish greeting", True),
            ("hey", "greeting", "Casual greeting", True),
            ("goodbye", "farewell", "Farewell, not greeting", False),
        ]

        for input_text, intent, description, success in examples:
            print(f"✓ Teaching: '{input_text}' -> {description}")
            example = TrainingExample(
                input_text=input_text,
                expected_output=description,
                intent=intent,
                success=success,
                timestamp=datetime.now().timestamp()
            )
            self.training_system.learn_from_example(example)
            self.examples_learned += 1
            if success:
                self.training_system.reward_system.reward_success(intent, magnitude=1.5)
            time.sleep(0.1)

        print(f"\n✅ Taught {len(examples)} greeting examples")
        print_progress(self.training_system)

    def teach_command_concepts(self) -> None:
        """Teach command recognition"""
        print_header("STAGE 2: Teaching Command Concepts")

        examples = [
            ("open file explorer", "command", "Open file manager", True),
            ("take a screenshot", "command", "Capture screen", True),
            ("close this window", "command", "Close app window", True),
            ("create a new file", "command", "File creation", True),
            ("delete the folder", "command", "Folder deletion", True),
            ("what time is it", "question", "Question, not command", False),
        ]

        for input_text, intent, description, success in examples:
            print(f"✓ Teaching: '{input_text}' -> {description}")
            example = TrainingExample(
                input_text=input_text,
                expected_output=description,
                intent=intent,
                success=success,
                timestamp=datetime.now().timestamp()
            )
            self.training_system.learn_from_example(example)
            self.examples_learned += 1
            if success:
                self.training_system.reward_system.reward_success(intent, magnitude=1.2)
            time.sleep(0.1)

        print(f"\n✅ Taught {len(examples)} command examples")
        print_progress(self.training_system)

    def teach_question_concepts(self) -> None:
        """Teach question recognition"""
        print_header("STAGE 3: Teaching Question Concepts")

        examples = [
            ("what is the weather", "question", "Information request", True),
            ("how do I save this", "question", "How-to question", True),
            ("why is this happening", "question", "Reason question", True),
            ("tell me about Python", "question", "Information request", True),
            ("who are you", "question", "Identity question", True),
            ("close my browser", "command", "Command, not question", False),
        ]

        for input_text, intent, description, success in examples:
            print(f"✓ Teaching: '{input_text}' -> {description}")
            example = TrainingExample(
                input_text=input_text,
                expected_output=description,
                intent=intent,
                success=success,
                timestamp=datetime.now().timestamp()
            )
            self.training_system.learn_from_example(example)
            self.examples_learned += 1
            if success:
                self.training_system.reward_system.reward_success(intent, magnitude=1.1)
            time.sleep(0.1)

        print(f"\n✅ Taught {len(examples)} question examples")
        print_progress(self.training_system)

    def teach_with_feedback_corrections(self) -> None:
        """Teach through feedback and corrections"""
        print_header("STAGE 4: Learning from Corrections")

        # Simulate incorrect predictions followed by corrections
        corrections = [
            ("open the file", "command", "File opening", "I meant to open files"),
            ("what's the time", "question", "Time request", "I meant asking about time"),
            ("say hello back", "greeting", "Interactive greeting", "I meant to greet you"),
        ]

        for input_text, intent, expected, feedback_msg in corrections:
            print(f"⚠️  Correction: '{input_text}'")
            print(f"   Feedback: {feedback_msg}")

            self.training_system.feedback_loop.record_correction(
                user_input=input_text,
                bot_output=f"Wrong: {intent}",
                correct_output=expected,
                intent=intent
            )

            processed = self.training_system.feedback_loop.process_corrections()
            if processed:
                for ex in processed:
                    self.training_system.learn_from_example(ex)
                    self.corrections_made += 1
                    self.training_system.reward_system.reward_success(
                        f"correction_{intent}", magnitude=2.0
                    )

            time.sleep(0.2)

        print(f"\n✅ Processed {self.corrections_made} corrections")
        print_progress(self.training_system)

    def test_predictions(self) -> None:
        """Test what Elyan learned"""
        print_header("STAGE 5: Testing Predictions")

        test_cases = [
            ("hello world", "greeting"),
            ("open my files", "command"),
            ("what time is it", "question"),
            ("merhaba", "greeting"),
            ("create new file", "command"),
            ("why does this happen", "question"),
        ]

        correct_predictions = 0
        for input_text, expected_intent in test_cases:
            action, confidence = self.training_system.get_prediction(input_text)
            status = "✓" if action else "?"
            print(f"{status} '{input_text}'")
            print(f"   Action: {action}, Confidence: {confidence:.1%}")

            if action and confidence > 0.5:
                correct_predictions += 1

        accuracy = (correct_predictions / len(test_cases)) * 100
        print(f"\n✅ Prediction Accuracy: {accuracy:.0f}%")

    def advance_learning_level(self) -> None:
        """Advance to next learning level"""
        print_header("STAGE 6: Advancing Learning Level")

        current_level = self.training_system.learning_level
        print(f"Current Level: {current_level.name}")

        if self.examples_learned >= 15:
            self.training_system.advance_learning_level()
            new_level = self.training_system.learning_level
            print(f"✅ Advanced to: {new_level.name}")
        else:
            print(f"⚠️  Need more examples to advance (have {self.examples_learned}, need 15)")

    def show_final_summary(self) -> None:
        """Show final training summary"""
        print_header("Training Session Complete")

        duration = datetime.now() - self.session_start
        metrics = self.training_system.get_learning_metrics()

        print(f"📈 Final Metrics:")
        print(f"   Duration: {duration.total_seconds():.1f}s")
        print(f"   Examples Learned: {self.examples_learned}")
        print(f"   Corrections Processed: {self.corrections_made}")
        print(f"   Total Patterns: {metrics['total_patterns']}")
        print(f"   Learning Level: {metrics['learning_level']}")
        print(f"   Average Confidence: {metrics['avg_confidence']}")
        print(f"   Average Success Rate: {metrics['avg_success_rate']}")
        print(f"   Total Reward: {metrics['reward_score']}")
        print(f"   Overall Progress: {metrics['progress']}")

        print(f"\n✅ Training session complete!")
        print(f"💾 Data saved to: ~/.elyan/training.db")


def main() -> int:
    """Run training session"""
    print_header("Elyan Training System - Teaching the Bot")

    print("This demonstrates how Elyan learns progressively:")
    print("1. Start with exact matches (high confidence)")
    print("2. Learn from examples and rewards")
    print("3. Advance through learning levels")
    print("4. Learn from user corrections")
    print("5. Make predictions with confidence")
    print()

    session = TrainingSession()

    try:
        session.teach_greeting_concepts()
        time.sleep(0.5)

        session.teach_command_concepts()
        time.sleep(0.5)

        session.teach_question_concepts()
        time.sleep(0.5)

        session.teach_with_feedback_corrections()
        time.sleep(0.5)

        session.test_predictions()
        time.sleep(0.5)

        session.advance_learning_level()
        time.sleep(0.5)

        session.show_final_summary()

        return 0

    except Exception as e:
        logger.error(f"Training error: {e}", exc_info=True)
        print(f"\n❌ Error during training: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
