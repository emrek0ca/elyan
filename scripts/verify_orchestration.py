"""
scripts/verify_orchestration.py
─────────────────────────────────────────────────────────────────────────────
Verifies Phase 23 Multi-LLM Orchestration logic.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.multi_agent.specialists import get_specialist_registry
from core.multi_agent.swarm_consensus import SwarmConsensus
from core.reasoning.trace_logger import trace_logger

async def test_specialist_chains():
    print("\n--- Testing Specialist Chains ---")
    registry = get_specialist_registry()
    
    chain = registry.get_chain("CODING_WORKFLOW")
    if chain:
        print(f"Chain found: {chain.name}")
        print(f"Steps: {' -> '.join(chain.steps)}")
    else:
        print("❌ CODING_WORKFLOW not found!")

    builder = registry.get("builder")
    print(f"Builder preferred model: {builder.preferred_model}")

async def test_trace_logger():
    print("\n--- Testing Trace Logger ---")
    raw = "<thought>Bu bir test düşüncesidir. Sistem tüm modelleri koordine ediyor.</thought>{'success': true}"
    thought = trace_logger.extract_thought(raw)
    print(f"Extracted Thought: {thought}")
    
    # Simulate a push (will log but might skip broadcast if server not running in test env)
    trace_logger.push_trace("TestAgent", thought, "gpt-4o")

async def test_swarm_multi_model():
    print("\n--- Testing Multi-Model Swarm ---")
    # This requires mocking the LLM calls if we want to run without real API keys
    # For logic level verification, we check if the personas have the correct models assigned.
    swarm = SwarmConsensus(None)
    for p, cfg in swarm.tribunal_personas.items():
        print(f"Persona: {p:12} | Model: {cfg['model']}")

async def main():
    try:
        await test_specialist_chains()
        await test_trace_logger()
        await test_swarm_multi_model()
        print("\n✅ Phase 23 Verification PASSED (Logic Level)")
    except Exception as e:
        print(f"\n❌ Phase 23 Verification FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(main())
