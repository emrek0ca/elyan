"""
core/quota.py
─────────────────────────────────────────────────────────────────────────────
Quota and Usage Tracking for Elyan Monetization.
Tracks daily message counts and monthly token usage per user.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config.elyan_config import elyan_config
from core.subscription import subscription_manager
from utils.logger import get_logger

logger = get_logger("quota")

QUOTA_FILE = Path.home() / ".elyan" / "user_usage.json"

class QuotaManager:
    """Manages and tracks user quotas and message limits."""

    def __init__(self):
        self.db_path = QUOTA_FILE
        self._usage: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            if self.db_path.exists():
                content = self.db_path.read_text(encoding="utf-8")
                self._usage = json.loads(content)
            else:
                self._usage = {}
        except Exception as e:
            logger.error(f"Failed to load user usage: {e}")
            self._usage = {}

    def _save(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_text(
                json.dumps(self._usage, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save user usage: {e}")

    def _get_user_usage(self, user_id: str) -> Dict[str, Any]:
        uid = str(user_id or "local")
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        
        if uid not in self._usage:
            self._usage[uid] = {
                "daily": {},
                "monthly": {},
                "lifetime_messages": 0,
                "lifetime_tokens": 0,
                "last_active": int(time.time())
            }
        
        user_data = self._usage[uid]
        
        # Initialize daily usage if missing
        if today not in user_data["daily"]:
            user_data["daily"][today] = {"messages": 0, "tokens": 0}
            # Clean up old days (keep last 7 days)
            days = sorted(user_data["daily"].keys())
            if len(days) > 7:
                for d in days[:-7]:
                    del user_data["daily"][d]
                    
        # Initialize monthly usage if missing
        if month not in user_data["monthly"]:
            user_data["monthly"][month] = {"messages": 0, "tokens": 0}
            # Clean up old months (keep last 3 months)
            months = sorted(user_data["monthly"].keys())
            if len(months) > 3:
                for m in months[:-3]:
                    del user_data["monthly"][m]
                    
        return user_data

    def record_message(self, user_id: str, tokens: int = 0):
        """Record a single message and its token usage."""
        uid = str(user_id or "local")
        usage = self._get_user_usage(uid)
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        
        usage["daily"][today]["messages"] += 1
        usage["daily"][today]["tokens"] += max(0, tokens)
        usage["monthly"][month]["messages"] += 1
        usage["monthly"][month]["tokens"] += max(0, tokens)
        usage["lifetime_messages"] += 1
        usage["lifetime_tokens"] += max(0, tokens)
        usage["last_active"] = int(time.time())
        
        self._save()

    def check_quota(self, user_id: str) -> dict[str, Any]:
        """
        Checks if a user has exceeded their tier-based quota.
        Returns a dictionary with 'allowed' (bool) and 'reason' (str).
        """
        # If monetization is not enabled, everyone is allowed.
        if not elyan_config.config.subscriptions.enabled:
            return {"allowed": True, "reason": "subscriptions_disabled"}

        uid = str(user_id or "local")

        # Local/CLI users are unlimited — quota only applies to external channel users
        if uid in ("local", "cli", "system", "test_user", ""):
            return {"allowed": True, "reason": "local_user_unlimited"}
        tier = subscription_manager.get_user_tier(uid)
        limits = subscription_manager.get_tier_limits(tier)
        
        usage = self._get_user_usage(uid)
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        
        daily_msgs = usage["daily"][today]["messages"]
        monthly_tokens = usage["monthly"][month]["tokens"]
        
        # Check message limit
        max_msgs = int(limits.get("max_messages_daily", 20))
        if max_msgs != -1 and daily_msgs >= max_msgs:
            return {
                "allowed": False, 
                "reason": "daily_message_limit_reached",
                "tier": tier.value,
                "current": daily_msgs,
                "limit": max_msgs
            }
            
        # Check token limit
        max_tokens = int(limits.get("max_tokens_monthly", 100000))
        if max_tokens != -1 and monthly_tokens >= max_tokens:
            return {
                "allowed": False, 
                "reason": "monthly_token_limit_reached",
                "tier": tier.value,
                "current": monthly_tokens,
                "limit": max_tokens
            }
            
        return {"allowed": True, "reason": "within_limits"}

    def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """Detailed usage statistics for a user."""
        uid = str(user_id or "local")
        usage = self._get_user_usage(uid)
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        
        tier = subscription_manager.get_user_tier(uid)
        limits = subscription_manager.get_tier_limits(tier)
        
        return {
            "tier": tier.value,
            "daily_messages": usage["daily"][today]["messages"],
            "daily_limit": int(limits.get("max_messages_daily", 20)),
            "monthly_tokens": usage["monthly"][month]["tokens"],
            "monthly_limit": int(limits.get("max_tokens_monthly", 100000)),
            "lifetime_messages": usage["lifetime_messages"],
            "lifetime_tokens": usage["lifetime_tokens"],
        }

# Singleton
quota_manager = QuotaManager()
