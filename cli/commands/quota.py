"""
CLI command handler for quota management.
"""

from __future__ import annotations

from core.quota import quota_manager

def run(args):
    subcommand = getattr(args, "subcommand", "status")
    
    if subcommand == "status":
        user_id = getattr(args, "user", "local") or "local"
        stats = quota_manager.get_user_stats(user_id)
        
        print(f"\nQuota status for User: {user_id}")
        print(f"Current Tier: {stats['tier'].upper()}")
        
        daily_limit = stats['daily_limit']
        daily_limit_str = str(daily_limit) if daily_limit != -1 else "Unlimited"
        print(f"\nDaily Messages: {stats['daily_messages']} / {daily_limit_str}")
        
        monthly_limit = stats['monthly_limit']
        monthly_limit_str = str(monthly_limit) if monthly_limit != -1 else "Unlimited"
        print(f"Monthly Tokens: {stats['monthly_tokens']} / {monthly_limit_str}")
        
        print(f"\nLifetime Messages: {stats['lifetime_messages']}")
        print(f"Lifetime Tokens: {stats['lifetime_tokens']}")

    elif subcommand == "check":
        user_id = getattr(args, "user", "local") or "local"
        result = quota_manager.check_quota(user_id)
        
        if result["allowed"]:
            print(f"✅ User {user_id} is within limits. Reason: {result['reason']}")
        else:
            print(f"❌ User {user_id} has exceeded limits! Reason: {result['reason']}")
            if "limit" in result:
                print(f"   Current: {result['current']}, Limit: {result['limit']}")
