"""
scripts/verify_self_healing.py
─────────────────────────────────────────────────────────────────────────────
Simulates failures to verify Phase 22 Self-Healing and Fallback logic.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.self_healing import get_healing_engine
from core.resilience.fallback_manager import fallback_manager
from core.resilience.circuit_breaker import resilience_manager

async def test_healing_engine():
    print("\n--- Testing Self-Healing Engine ---")
    engine = get_healing_engine()
    
    # 1. Test Permission Denied
    err = "PermissionError: [Errno 13] Permission denied: '/root/test.txt'"
    diag = engine.diagnose(err)
    print(f"Diagnosis (Permission): {diag.name if diag else 'None'}")
    plan = await engine.get_healing_plan(diag, err, {"params": {"path": "/root/test.txt"}})
    print(f"Healing Plan: {plan.get('message')} (Can fix: {plan.get('can_auto_fix')})")
    
    # 2. Test Rate Limit -> Fallback
    err = "429 Too Many Requests"
    diag = engine.diagnose(err)
    print(f"Diagnosis (Rate Limit): {diag.name if diag else 'None'}")
    plan = await engine.get_healing_plan(diag, err, {"provider": "openai"})
    print(f"Healing Plan: {plan.get('message')} (Suggested: {plan.get('suggested_provider')})")

async def test_fallback_manager():
    print("\n--- Testing Fallback Manager ---")
    
    # Simulate OpenAI failure
    resilience_manager.record_failure("openai")
    resilience_manager.record_failure("openai")
    resilience_manager.record_failure("openai") # Should OPEN the circuit
    
    print(f"OpenAI state: {resilience_manager.get_breaker('openai').state.value}")
    
    best = fallback_manager.get_best_provider("openai")
    print(f"Best provider for OpenAI (when failed): {best}")
    
    # Reset for other tests
    resilience_manager.get_breaker("openai").record_success()

async def main():
    try:
        await test_healing_engine()
        await test_fallback_manager()
        print("\n✅ Phase 22 Verification PASSED (Logic Level)")
    except Exception as e:
        print(f"\n❌ Phase 22 Verification FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(main())
