"""
ELYAN Subscription & Billing System - Phase 8
Tier management, usage tracking, cost optimization.
"""

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SubscriptionTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class BillingCycle(Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class UsageType(Enum):
    API_REQUEST = "api_request"
    LLM_TOKEN = "llm_token"
    CODE_GENERATION = "code_generation"
    STORAGE_MB = "storage_mb"
    AGENT_EXECUTION = "agent_execution"
    WEBHOOK_DELIVERY = "webhook_delivery"


TIER_LIMITS = {
    SubscriptionTier.FREE: {
        UsageType.API_REQUEST: 100,
        UsageType.LLM_TOKEN: 50000,
        UsageType.CODE_GENERATION: 10,
        UsageType.STORAGE_MB: 100,
        UsageType.AGENT_EXECUTION: 5,
        UsageType.WEBHOOK_DELIVERY: 10,
    },
    SubscriptionTier.PRO: {
        UsageType.API_REQUEST: 10000,
        UsageType.LLM_TOKEN: 5000000,
        UsageType.CODE_GENERATION: 1000,
        UsageType.STORAGE_MB: 5000,
        UsageType.AGENT_EXECUTION: 500,
        UsageType.WEBHOOK_DELIVERY: 1000,
    },
    SubscriptionTier.ENTERPRISE: {
        UsageType.API_REQUEST: -1,
        UsageType.LLM_TOKEN: -1,
        UsageType.CODE_GENERATION: -1,
        UsageType.STORAGE_MB: -1,
        UsageType.AGENT_EXECUTION: -1,
        UsageType.WEBHOOK_DELIVERY: -1,
    },
}

TIER_PRICING = {
    SubscriptionTier.FREE: {"monthly": 0, "annual": 0},
    SubscriptionTier.PRO: {"monthly": 29, "annual": 290},
    SubscriptionTier.ENTERPRISE: {"monthly": 999, "annual": 9990},
}

TIER_FEATURES = {
    SubscriptionTier.FREE: [
        "basic_models", "community_support", "single_workspace",
    ],
    SubscriptionTier.PRO: [
        "all_models", "priority_support", "5_workspaces",
        "advanced_analytics", "webhook_support", "api_access",
    ],
    SubscriptionTier.ENTERPRISE: [
        "all_models", "dedicated_support", "unlimited_workspaces",
        "sso", "audit_logging", "custom_models", "sla_guarantee",
        "data_residency", "rbac", "api_access", "webhook_support",
    ],
}


@dataclass
class Subscription:
    subscription_id: str
    user_id: str
    tier: SubscriptionTier
    cycle: BillingCycle
    status: str = "active"
    created_at: float = 0.0
    current_period_start: float = 0.0
    current_period_end: float = 0.0
    cancel_at_period_end: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == "active" and time.time() < self.current_period_end

    @property
    def days_remaining(self) -> int:
        remaining = self.current_period_end - time.time()
        return max(0, int(remaining / 86400))


@dataclass
class UsageRecord:
    record_id: str
    user_id: str
    usage_type: UsageType
    amount: int
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Invoice:
    invoice_id: str
    user_id: str
    amount: float
    currency: str = "USD"
    status: str = "pending"
    created_at: float = 0.0
    paid_at: float = 0.0
    line_items: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"


class UsageTracker:
    """Track and enforce usage limits per user."""

    def __init__(self):
        self._usage: Dict[str, Dict[UsageType, int]] = defaultdict(lambda: defaultdict(int))
        self._records: List[UsageRecord] = []
        self._period_start: Dict[str, float] = {}

    def record(self, user_id: str, usage_type: UsageType, amount: int = 1, **metadata) -> UsageRecord:
        record = UsageRecord(
            record_id=f"usage_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            usage_type=usage_type,
            amount=amount,
            timestamp=time.time(),
            metadata=metadata,
        )
        self._usage[user_id][usage_type] += amount
        self._records.append(record)
        return record

    def get_usage(self, user_id: str) -> Dict[UsageType, int]:
        return dict(self._usage.get(user_id, {}))

    def check_limit(self, user_id: str, usage_type: UsageType, tier: SubscriptionTier) -> Dict[str, Any]:
        current = self._usage.get(user_id, {}).get(usage_type, 0)
        limit = TIER_LIMITS.get(tier, {}).get(usage_type, 0)
        if limit == -1:
            return {"allowed": True, "current": current, "limit": "unlimited", "remaining": "unlimited"}
        remaining = max(0, limit - current)
        return {
            "allowed": current < limit,
            "current": current,
            "limit": limit,
            "remaining": remaining,
            "usage_percent": round((current / max(1, limit)) * 100, 1),
        }

    def reset_period(self, user_id: str):
        self._usage[user_id] = defaultdict(int)
        self._period_start[user_id] = time.time()

    def get_cost_breakdown(self, user_id: str) -> Dict[str, Any]:
        usage = self.get_usage(user_id)
        cost_per_unit = {
            UsageType.API_REQUEST: 0.001,
            UsageType.LLM_TOKEN: 0.00001,
            UsageType.CODE_GENERATION: 0.05,
            UsageType.STORAGE_MB: 0.01,
            UsageType.AGENT_EXECUTION: 0.02,
            UsageType.WEBHOOK_DELIVERY: 0.001,
        }
        breakdown = {}
        total = 0.0
        for usage_type, amount in usage.items():
            cost = amount * cost_per_unit.get(usage_type, 0)
            breakdown[usage_type.value] = {"amount": amount, "unit_cost": cost_per_unit.get(usage_type, 0), "total_cost": round(cost, 4)}
            total += cost
        return {"breakdown": breakdown, "total_cost": round(total, 4), "currency": "USD"}


class SubscriptionManager:
    """Manage user subscriptions and billing."""

    def __init__(self):
        self._subscriptions: Dict[str, Subscription] = {}
        self._invoices: List[Invoice] = []
        self.usage_tracker = UsageTracker()

    def create_subscription(
        self,
        user_id: str,
        tier: SubscriptionTier = SubscriptionTier.FREE,
        cycle: BillingCycle = BillingCycle.MONTHLY,
    ) -> Subscription:
        now = time.time()
        period_days = 30 if cycle == BillingCycle.MONTHLY else 365
        sub = Subscription(
            subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            tier=tier,
            cycle=cycle,
            created_at=now,
            current_period_start=now,
            current_period_end=now + (period_days * 86400),
        )
        self._subscriptions[user_id] = sub
        if tier != SubscriptionTier.FREE:
            self._create_invoice(user_id, tier, cycle)
        return sub

    def upgrade(self, user_id: str, new_tier: SubscriptionTier) -> Optional[Subscription]:
        sub = self._subscriptions.get(user_id)
        if not sub:
            return None
        old_tier = sub.tier
        sub.tier = new_tier
        if new_tier != SubscriptionTier.FREE:
            self._create_invoice(user_id, new_tier, sub.cycle)
        return sub

    def downgrade(self, user_id: str, new_tier: SubscriptionTier) -> Optional[Subscription]:
        sub = self._subscriptions.get(user_id)
        if not sub:
            return None
        sub.tier = new_tier
        sub.cancel_at_period_end = False
        return sub

    def cancel(self, user_id: str, immediate: bool = False) -> Optional[Subscription]:
        sub = self._subscriptions.get(user_id)
        if not sub:
            return None
        if immediate:
            sub.status = "cancelled"
            sub.current_period_end = time.time()
        else:
            sub.cancel_at_period_end = True
        return sub

    def get_subscription(self, user_id: str) -> Optional[Subscription]:
        return self._subscriptions.get(user_id)

    def get_features(self, user_id: str) -> List[str]:
        sub = self._subscriptions.get(user_id)
        if not sub:
            return TIER_FEATURES[SubscriptionTier.FREE]
        return TIER_FEATURES.get(sub.tier, [])

    def check_feature(self, user_id: str, feature: str) -> bool:
        return feature in self.get_features(user_id)

    def check_usage(self, user_id: str, usage_type: UsageType) -> Dict[str, Any]:
        sub = self._subscriptions.get(user_id)
        tier = sub.tier if sub else SubscriptionTier.FREE
        return self.usage_tracker.check_limit(user_id, usage_type, tier)

    def record_usage(self, user_id: str, usage_type: UsageType, amount: int = 1) -> Dict[str, Any]:
        limit_check = self.check_usage(user_id, usage_type)
        if not limit_check["allowed"]:
            return {"recorded": False, "reason": "limit_exceeded", **limit_check}
        self.usage_tracker.record(user_id, usage_type, amount)
        return {"recorded": True, **limit_check}

    def _create_invoice(self, user_id: str, tier: SubscriptionTier, cycle: BillingCycle):
        pricing = TIER_PRICING.get(tier, {})
        amount = pricing.get(cycle.value, 0)
        invoice = Invoice(
            invoice_id=f"inv_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            amount=amount,
            created_at=time.time(),
            line_items=[{
                "description": f"ELYAN {tier.value.title()} - {cycle.value.title()}",
                "amount": amount,
            }],
        )
        self._invoices.append(invoice)
        return invoice

    def get_invoices(self, user_id: str) -> List[Invoice]:
        return [inv for inv in self._invoices if inv.user_id == user_id]

    def get_billing_summary(self, user_id: str) -> Dict[str, Any]:
        sub = self.get_subscription(user_id)
        invoices = self.get_invoices(user_id)
        usage = self.usage_tracker.get_usage(user_id)
        cost = self.usage_tracker.get_cost_breakdown(user_id)
        return {
            "subscription": {
                "tier": sub.tier.value if sub else "free",
                "status": sub.status if sub else "none",
                "days_remaining": sub.days_remaining if sub else 0,
            },
            "usage": {k.value: v for k, v in usage.items()},
            "cost": cost,
            "invoices": len(invoices),
            "features": self.get_features(user_id),
        }
