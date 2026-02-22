"""
core/reasoning/multi_model_router.py
─────────────────────────────────────────────────────────────────────────────
Multi-Model LLM Orchestrator (Phase 36).
Automatically routes tasks to the optimal LLM based on task type,
complexity, cost budget, and model strengths.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from utils.logger import get_logger

logger = get_logger("multi_model")

class TaskType(Enum):
    CODE = "code"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    TRANSLATION = "translation"
    MATH = "math"
    CONVERSATION = "conversation"
    RESEARCH = "research"

@dataclass
class ModelProfile:
    name: str
    provider: str  # openai, anthropic, google, local
    strengths: List[TaskType]
    cost_per_1k_tokens: float
    max_context: int
    speed_rating: float  # 0-1, higher = faster
    quality_rating: float  # 0-1, higher = better
    available: bool = True

@dataclass
class RouteDecision:
    model: ModelProfile
    reason: str
    estimated_cost: float

# Model Registry — extensible by user config
MODEL_REGISTRY: List[ModelProfile] = [
    ModelProfile(
        name="gemini-2.0-flash",
        provider="google",
        strengths=[TaskType.CODE, TaskType.ANALYSIS, TaskType.CONVERSATION],
        cost_per_1k_tokens=0.0,
        max_context=1000000,
        speed_rating=0.9,
        quality_rating=0.85,
        available=True
    ),
    ModelProfile(
        name="gemini-2.5-pro",
        provider="google",
        strengths=[TaskType.CODE, TaskType.ANALYSIS, TaskType.MATH, TaskType.RESEARCH],
        cost_per_1k_tokens=0.01,
        max_context=1000000,
        speed_rating=0.7,
        quality_rating=0.95,
        available=True
    ),
    ModelProfile(
        name="claude-3.5-sonnet",
        provider="anthropic",
        strengths=[TaskType.CODE, TaskType.CREATIVE, TaskType.ANALYSIS],
        cost_per_1k_tokens=0.015,
        max_context=200000,
        speed_rating=0.8,
        quality_rating=0.92,
        available=False  # Needs API key
    ),
    ModelProfile(
        name="gpt-4o",
        provider="openai",
        strengths=[TaskType.CODE, TaskType.CREATIVE, TaskType.CONVERSATION],
        cost_per_1k_tokens=0.01,
        max_context=128000,
        speed_rating=0.8,
        quality_rating=0.90,
        available=False
    ),
    ModelProfile(
        name="llama-3.1-70b",
        provider="local",
        strengths=[TaskType.CONVERSATION, TaskType.TRANSLATION],
        cost_per_1k_tokens=0.0,
        max_context=128000,
        speed_rating=0.5,
        quality_rating=0.75,
        available=False  # Needs local setup
    ),
    ModelProfile(
        name="groq-llama-3.3-70b",
        provider="groq",
        strengths=[TaskType.CODE, TaskType.CONVERSATION, TaskType.ANALYSIS],
        cost_per_1k_tokens=0.0,
        max_context=128000,
        speed_rating=0.95,
        quality_rating=0.80,
        available=True
    ),
]

class MultiModelRouter:
    def __init__(self, budget_limit: float = 1.0):
        self.budget_limit = budget_limit  # Max $ per day
        self.daily_spend = 0.0
        self.last_reset = time.time()
        self._usage_stats: Dict[str, int] = {}
    
    def route(self, task_type: TaskType, priority: str = "balanced",
              context_length: int = 0) -> RouteDecision:
        """Select the optimal model for a given task."""
        self._check_daily_reset()
        
        available = [m for m in MODEL_REGISTRY if m.available]
        if not available:
            fallback = MODEL_REGISTRY[0]
            return RouteDecision(model=fallback, reason="No models available, using default", estimated_cost=0)
        
        # Score each model
        scores = []
        for model in available:
            score = 0.0
            
            # Strength match
            if task_type in model.strengths:
                score += 3.0
            
            # Context fit
            if context_length <= model.max_context:
                score += 1.0
            else:
                score -= 10.0  # Disqualify
            
            # Priority weighting
            if priority == "quality":
                score += model.quality_rating * 3
            elif priority == "speed":
                score += model.speed_rating * 3
            elif priority == "cost":
                score += (1 - min(model.cost_per_1k_tokens * 100, 1)) * 3
            else:  # balanced
                score += model.quality_rating * 1.5 + model.speed_rating * 1.0 + (1 - min(model.cost_per_1k_tokens * 100, 1)) * 0.5
            
            # Budget check
            estimated_cost = model.cost_per_1k_tokens * (context_length / 1000)
            if self.daily_spend + estimated_cost > self.budget_limit:
                score -= 5.0
            
            scores.append((model, score, estimated_cost))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        best_model, best_score, est_cost = scores[0]
        
        self.daily_spend += est_cost
        self._usage_stats[best_model.name] = self._usage_stats.get(best_model.name, 0) + 1
        
        decision = RouteDecision(
            model=best_model,
            reason=f"Best fit for {task_type.value} (score={best_score:.1f}, priority={priority})",
            estimated_cost=est_cost
        )
        
        logger.info(f"🎯 Routed to {best_model.name}: {decision.reason}")
        return decision
    
    def _check_daily_reset(self):
        if time.time() - self.last_reset > 86400:
            self.daily_spend = 0.0
            self.last_reset = time.time()
    
    def get_stats(self) -> Dict:
        return {
            "daily_spend": round(self.daily_spend, 4),
            "budget_remaining": round(self.budget_limit - self.daily_spend, 4),
            "usage": self._usage_stats
        }

# Global singleton
model_router = MultiModelRouter()
