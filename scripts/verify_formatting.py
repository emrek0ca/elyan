#!/usr/bin/env python3
"""
scripts/verify_formatting.py
─────────────────────────────────────────────────────────────────────────────
Verifies tool result formatting for new free APIs.
"""
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent

def test_format(name: str, result: Any):
    agent = Agent()
    output = agent._format_result_text(result)
    print(f"--- {name} ---")
    print(output)
    print("-" * (len(name) + 8))
    
    # Validation checks
    if "İşlem başarıyla tamamlandı" in output:
        print(f"❌ {name} is STILL using generic success message!")
        return False
    return True

def main():
    print("🎨 Elyan Response Formatting Verification\n")
    success_count = 0
    total = 0
    
    # 1. Crypto
    total += 1
    if test_format("Crypto", {
        "success": True,
        "prices": {"bitcoin": {"price": 64203, "change_24h": -1.04}},
        "vs_currency": "usd"
    }): success_count += 1
    
    # 2. Exchange Rate
    total += 1
    if test_format("Exchange Rate", {
        "success": True,
        "base": "USD",
        "rates": {"TRY": 31.25, "EUR": 0.92}
    }): success_count += 1
    
    # 3. Wikipedia
    total += 1
    if test_format("Wikipedia", {
        "success": True,
        "topic": "Python",
        "summary": "Python is a programming language.",
        "url": "https://en.wikipedia.org/wiki/Python"
    }): success_count += 1
    
    # 4. Dictionary
    total += 1
    if test_format("Dictionary", {
        "success": True,
        "word": "hello",
        "definitions": ["A greeting.", "An expression of surprise."]
    }): success_count += 1
    
    # 5. Weather
    total += 1
    if test_format("Weather", {
        "success": True,
        "city": "Istanbul",
        "temperature": 15.5,
        "description": "Partly Cloudy",
        "humidity": 60,
        "wind_speed": 12.5
    }): success_count += 1
    
    # 6. Country
    total += 1
    if test_format("Country", {
        "success": True,
        "name": "Turkey",
        "flag": "🇹🇷",
        "capital": "Ankara",
        "population": 85000000,
        "region": "Asia/Europe"
    }): success_count += 1
    
    # 7. Advice
    total += 1
    if test_format("Advice", {
        "success": True,
        "advice": "Drink more water."
    }): success_count += 1

    print(f"\nFinal Result: {success_count}/{total} PASSED")
    return 0 if success_count == total else 1

if __name__ == "__main__":
    sys.exit(main())
