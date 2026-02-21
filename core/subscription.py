"""
core/subscription.py
─────────────────────────────────────────────────────────────────────────────
User Subscription and Tier Management for Elyan.
Handles user-tier mapping, persisting state, and tier-specific features.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from config.elyan_config import elyan_config
from core.domain.models import SubscriptionTier
from utils.logger import get_logger

logger = get_logger("subscription")

SUBSCRIPTION_FILE = Path.home() / ".elyan" / "subscriptions.json"

class SubscriptionManager:
    """Manages user subscription status and tiers."""

    def __init__(self):
        self.db_path = SUBSCRIPTION_FILE
        self._users: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        try:
            if self.db_path.exists():
                content = self.db_path.read_text(encoding="utf-8")
                self._users = json.loads(content)
            else:
                self._users = {}
        except Exception as e:
            logger.error(f"Failed to load subscriptions: {e}")
            self._users = {}

    def _save(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_text(
                json.dumps(self._users, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save subscriptions: {e}")

    def get_user_tier(self, user_id: str) -> SubscriptionTier:
        """Get the current subscription tier for a user."""
        uid = str(user_id or "local")
        user_data = self._users.get(uid)
        
        if not user_data:
            return elyan_config.config.subscriptions.default_tier
        
        tier_str = user_data.get("tier", elyan_config.config.subscriptions.default_tier.value)
        try:
            return SubscriptionTier(tier_str)
        except ValueError:
            return elyan_config.config.subscriptions.default_tier

    def set_user_tier(self, user_id: str, tier: SubscriptionTier, expiry_days: Optional[int] = None):
        """Set or update a user's subscription tier."""
        uid = str(user_id or "local")
        expiry_ts = 0
        if expiry_days:
            expiry_ts = int(time.time() + (expiry_days * 86400))
        
        self._users[uid] = {
            "tier": tier.value,
            "updated_at": int(time.time()),
            "expiry_at": expiry_ts,
            "status": "active"
        }
        self._save()
        logger.info(f"User {uid} tier set to {tier.value} (expires: {expiry_ts or 'never'})")

    def get_tier_limits(self, tier: SubscriptionTier) -> Dict[str, Any]:
        """Retrieve limits for a specific tier from config."""
        tiers_config = elyan_config.config.subscriptions.tiers
        return tiers_config.get(tier, tiers_config[SubscriptionTier.FREE])

    def check_feature_allowed(self, user_id: str, feature: str) -> bool:
        """Check if a specific feature is allowed for the user's tier."""
        tier = self.get_user_tier(user_id)
        limits = self.get_tier_limits(tier)
        return bool(limits.get(feature, False))

    def get_subscription_summary(self, user_id: str) -> Dict[str, Any]:
        """Detailed status summary for a user."""
        uid = str(user_id or "local")
        tier = self.get_user_tier(uid)
        limits = self.get_tier_limits(tier)
        user_data = self._users.get(uid, {})
        
        return {
            "user_id": uid,
            "tier": tier.value,
            "limits": limits,
            "expiry_at": user_data.get("expiry_at", 0),
            "status": user_data.get("status", "none")
        }

# Singleton
subscription_manager = SubscriptionManager()
