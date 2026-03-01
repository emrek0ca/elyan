#!/usr/bin/env python3
"""
scripts/verify_persona_fallback.py
─────────────────────────────────────────────────────────────────────────────
Verifies Elyan's persona (no API names) and tool-to-LLM fallback.
"""
import sys
import asyncio
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent
from core.pipeline import PipelineContext, StageExecute

async def test_fallback():
    agent = Agent()
    print("🎭 Elyan Persona & Fallback Verification\n")
    
    # 1. Test "ne demek" routing and LLM fallback
    # "camış" is not in the dictionary, should fallback to LLM
    ctx = PipelineContext(
        user_input="camış ne demek",
        action="get_word_definition", # Simulating intent finding
        intent={"action": "get_word_definition", "params": {"word": "camış", "lang": "en"}}
    )
    
    execute_stage = StageExecute()
    # We need to simulate the environment since we don't want to actually call LLM if possible,
    # or just observe that it doesn't stop at the tool error.
    
    # Actually, the best way is to check _run_direct_intent result.
    direct_text = await agent._run_direct_intent(ctx.intent, ctx.user_input, "inference", [])
    print(f"Query: 'camış ne demek'")
    print(f"Direct Response: {direct_text}")
    if direct_text is None:
        print("✅ Correct: Direct intent returned None (fallback to LLM triggered)")
    else:
        print("❌ Error: Direct intent should have returned None for unknown word")

    # 2. Test Persona (No Wikipedia/DuckDuckGo mentions)
    print("\nCheck Persona (Searching for 'Wikipedia', 'DuckDuckGo', etc. in responses):")
    results_to_check = [
        {"prices": {"bitcoin": {"price": 60000}}},
        {"topic": "Python", "summary": "A language.", "url": "..."},
        {"answer": "A result.", "query": "test"}
    ]
    
    banned_words = ["Wikipedia", "DuckDuckGo", "CoinGecko", "Open-Meteo", "Source"]
    for res in results_to_check:
        fmt = agent._format_result_text(res)
        print(f"Formatted: {fmt}")
        found = [w for w in banned_words if w.lower() in (fmt or "").lower()]
        if found:
            print(f"❌ Persona violation: Found {found}")
        else:
            print("✅ Persona OK")

if __name__ == "__main__":
    asyncio.run(test_fallback())
