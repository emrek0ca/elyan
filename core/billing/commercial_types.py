from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CommercialPlan:
    plan_id: str
    label: str
    monthly_price_try: int
    yearly_price_try: int
    included_credits: int
    seat_limit: int
    connector_limit: int
    artifact_limit: int
    premium_models: bool
    support_tier: str = "standard"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TokenPack:
    pack_id: str
    label: str
    credits: int
    price_try: int
    bonus_credits: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PLAN_CATALOG: dict[str, CommercialPlan] = {
    "free": CommercialPlan(
        plan_id="free",
        label="Free",
        monthly_price_try=0,
        yearly_price_try=0,
        included_credits=5000,
        seat_limit=1,
        connector_limit=2,
        artifact_limit=12,
        premium_models=False,
        support_tier="community",
    ),
    "pro": CommercialPlan(
        plan_id="pro",
        label="Pro",
        monthly_price_try=899,
        yearly_price_try=8990,
        included_credits=120000,
        seat_limit=1,
        connector_limit=8,
        artifact_limit=240,
        premium_models=True,
        support_tier="priority",
    ),
    "team": CommercialPlan(
        plan_id="team",
        label="Team",
        monthly_price_try=4999,
        yearly_price_try=49990,
        included_credits=600000,
        seat_limit=15,
        connector_limit=24,
        artifact_limit=1600,
        premium_models=True,
        support_tier="business",
    ),
    "enterprise": CommercialPlan(
        plan_id="enterprise",
        label="Enterprise",
        monthly_price_try=24999,
        yearly_price_try=249990,
        included_credits=5000000,
        seat_limit=250,
        connector_limit=200,
        artifact_limit=10000,
        premium_models=True,
        support_tier="enterprise",
        metadata={"manual_contract": True},
    ),
}


TOKEN_PACK_CATALOG: dict[str, TokenPack] = {
    "starter_25k": TokenPack(pack_id="starter_25k", label="Starter 25K", credits=25000, bonus_credits=0, price_try=299),
    "growth_100k": TokenPack(pack_id="growth_100k", label="Growth 100K", credits=100000, bonus_credits=5000, price_try=999),
    "scale_500k": TokenPack(pack_id="scale_500k", label="Scale 500K", credits=500000, bonus_credits=50000, price_try=3999),
}


def get_plan(plan_id: str) -> CommercialPlan:
    normalized = str(plan_id or "free").strip().lower() or "free"
    return PLAN_CATALOG.get(normalized, PLAN_CATALOG["free"])


def get_token_pack(pack_id: str) -> TokenPack:
    normalized = str(pack_id or "").strip().lower()
    if normalized not in TOKEN_PACK_CATALOG:
        raise KeyError(f"unknown_token_pack:{normalized or 'empty'}")
    return TOKEN_PACK_CATALOG[normalized]


__all__ = [
    "CommercialPlan",
    "TokenPack",
    "PLAN_CATALOG",
    "TOKEN_PACK_CATALOG",
    "get_plan",
    "get_token_pack",
]
