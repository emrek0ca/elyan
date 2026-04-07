from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RewardShaper:
    def compute_reward(
        self,
        task_completed: bool,
        user_explicit_feedback: float | None,
        response_time_ms: float,
        approval_required: bool,
        task_was_in_cache: bool,
        error_occurred: bool,
    ) -> float:
        reward = 1.0 if task_completed else -0.5
        if user_explicit_feedback is not None:
            reward += (max(0.0, min(1.0, float(user_explicit_feedback))) - 0.5) * 2.0
        if response_time_ms < 2000:
            reward += 0.3
        elif response_time_ms > 10000:
            reward -= 0.2
        if task_completed and not approval_required:
            reward += 0.2
        if task_was_in_cache:
            reward += 0.1
        if error_occurred:
            reward -= 0.3
        return max(-2.0, min(2.0, reward))
