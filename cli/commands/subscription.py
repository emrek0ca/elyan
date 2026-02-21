"""
CLI command handler for subscription management.
"""

from __future__ import annotations

from core.subscription import subscription_manager
from core.domain.models import SubscriptionTier

def run(args):
    subcommand = getattr(args, "subcommand", "status")
    
    if subcommand == "status":
        user_id = getattr(args, "user_id", "local") or "local"
        summary = subscription_manager.get_subscription_summary(user_id)
        
        print(f"\nUser: {summary['user_id']}")
        print(f"Tier: {summary['tier'].upper()}")
        print(f"Status: {summary['status']}")
        if summary['expiry_at'] > 0:
            import datetime
            expiry_date = datetime.datetime.fromtimestamp(summary['expiry_at']).strftime('%Y-%m-%d %H:%M:%S')
            print(f"Expires: {expiry_date}")
        else:
            print("Expires: Never")
            
        print("\nLimits:")
        for key, val in summary['limits'].items():
            print(f"  - {key}: {val}")

    elif subcommand == "set":
        user_id = getattr(args, "user_id", "local") or "local"
        tier_str = getattr(args, "tier", "free").lower()
        expiry_days = getattr(args, "days", None)
        
        try:
            tier = SubscriptionTier(tier_str)
            subscription_manager.set_user_tier(user_id, tier, expiry_days=expiry_days)
            print(f"✅ User {user_id} tier set to {tier.value}")
        except ValueError:
            print(f"❌ Invalid tier: {tier_str}. Choose from: free, pro, enterprise")

    elif subcommand == "list-tiers":
        from config.elyan_config import elyan_config
        tiers = elyan_config.config.subscriptions.tiers
        print("\nAvailable Tiers:")
        for tier, limits in tiers.items():
            print(f"\n[{tier.upper()}]")
            for key, val in limits.items():
                print(f"  - {key}: {val}")
