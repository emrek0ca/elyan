"""
Elyan Token Budget Manager — Real-time cost and usage tracking for LLM requests.

Enforces daily/monthly limits and tracks spend across providers.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("token_budget")

DB_PATH = Path.home() / ".elyan" / "compliance" / "usage.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class TokenBudgetManager:
    def __init__(self, daily_limit_usd: float = 5.0):
        self.daily_limit_usd = daily_limit_usd
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL
            )
        """)
        self.conn.commit()

    def record_usage(
        self, 
        user_id: str, 
        provider: str, 
        model: str, 
        prompt_tokens: int, 
        completion_tokens: int,
        cost_usd: float = 0.0
    ):
        """Record token usage and estimated cost."""
        try:
            self.conn.execute(
                "INSERT INTO usage_logs (timestamp, user_id, provider, model, prompt_tokens, completion_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), user_id, provider, model, prompt_tokens, completion_tokens, cost_usd)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to record token usage: {e}")

    def get_daily_spend(self, user_id: str = None) -> float:
        """Get total spend in USD for the current natural day."""
        start_of_day = time.time() - (time.time() % 86400)
        try:
            if user_id:
                cursor = self.conn.execute(
                    "SELECT SUM(cost_usd) FROM usage_logs WHERE user_id = ? AND timestamp >= ?",
                    (user_id, start_of_day)
                )
            else:
                cursor = self.conn.execute(
                    "SELECT SUM(cost_usd) FROM usage_logs WHERE timestamp >= ?",
                    (start_of_day,)
                )
            res = cursor.fetchone()
            return res[0] if res and res[0] else 0.0
        except Exception as e:
            logger.error(f"Failed to get daily spend: {e}")
            return 0.0

    def is_within_budget(self, user_id: str = None) -> bool:
        """Check if the total spend is below the daily threshold."""
        current_spend = self.get_daily_spend(user_id)
        if current_spend >= self.daily_limit_usd:
            logger.warning(f"Budget exceeded: ${current_spend:.4f} >= ${self.daily_limit_usd:.4f}")
            return False
        return True

    def get_usage_summary(self) -> Dict[str, Any]:
        """Get global usage summary."""
        try:
            cursor = self.conn.execute("SELECT provider, SUM(prompt_tokens), SUM(completion_tokens), SUM(cost_usd) FROM usage_logs GROUP BY provider")
            rows = cursor.fetchall()
            return {
                row[0]: {
                    "prompt_tokens": row[1],
                    "completion_tokens": row[2],
                    "total_cost": row[3]
                } for row in rows
            }
        except Exception as e:
            logger.error(f"Failed to get usage summary: {e}")
            return {}

# Global instance
token_budget = TokenBudgetManager()
