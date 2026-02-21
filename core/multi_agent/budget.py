"""
core/multi_agent/budget.py
─────────────────────────────────────────────────────────────────────────────
Budget Tracker for Autonomous Operations.
Enforces limits based on Job Templates to protect against infinite loops
and excessive API costs.
"""

from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("budget_tracker")

class BudgetExceededError(Exception):
    pass

@dataclass
class CostRates:
    input_token: float = 0.00000015 # Gemini 3.1 Pro estimation
    output_token: float = 0.00000060

class BudgetTracker:
    def __init__(self, max_tokens: int = 150000, max_usd: float = 0.5):
        self.max_tokens = max_tokens
        self.max_usd = max_usd
        
        self.used_input_tokens = 0
        self.used_output_tokens = 0
        
    @property
    def total_tokens(self) -> int:
        return self.used_input_tokens + self.used_output_tokens
        
    @property
    def total_cost_usd(self) -> float:
        return (self.used_input_tokens * CostRates.input_token) + (self.used_output_tokens * CostRates.output_token)

    def consume(self, input_tokens: int, output_tokens: int):
        """Adds usage to the budget and checks limits."""
        self.used_input_tokens += input_tokens
        self.used_output_tokens += output_tokens
        
        # Hard circuit breaking
        if self.total_tokens >= self.max_tokens:
            msg = f"Token Limit Exceeded: {self.total_tokens}/{self.max_tokens} tokens."
            logger.error(msg)
            raise BudgetExceededError(msg)
            
        if self.total_cost_usd >= self.max_usd:
            msg = f"Budget Exceeded: ${self.total_cost_usd:.4f}/${self.max_usd:.4f}"
            logger.error(msg)
            raise BudgetExceededError(msg)
            
    def get_status(self) -> str:
        return f"{self.total_tokens}/{self.max_tokens} t, ${self.total_cost_usd:.4f}/${self.max_usd:.4f}"
