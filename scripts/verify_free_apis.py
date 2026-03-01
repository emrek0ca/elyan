#!/usr/bin/env python3
"""
scripts/verify_free_apis.py
─────────────────────────────────────────────────────────────────────────────
Verifies all free API integrations (zero cost, no API key).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test_api(name: str, coro):
    try:
        result = await coro
        success = result.get("success", False)
        icon = "✅" if success else "❌"
        detail = ""
        if success:
            # Show a brief summary of the result
            for key in ["summary", "answer", "quote", "advice", "fact", "word", "prices", "base", "city", "name", "ip"]:
                if key in result:
                    val = str(result[key])[:80]
                    detail = f"  → {key}: {val}"
                    break
        else:
            detail = f"  → Error: {result.get('error', 'unknown')}"
        print(f"  {icon} {name}{detail}")
        return success
    except Exception as e:
        print(f"  ❌ {name}  → CRASH: {e}")
        return False


async def main():
    print("🌐 Elyan Free API Verification Suite\n")
    passed = 0
    total = 0

    # 1. Knowledge APIs
    print("📚 Knowledge & Language APIs:")
    from tools.free_apis.free_knowledge_apis import (
        get_wikipedia_summary, get_word_definition,
        get_random_advice, get_random_fact, get_random_quote
    )
    tests = [
        ("Wikipedia (Python)", get_wikipedia_summary("Python_(programming_language)")),
        ("Dictionary (hello)", get_word_definition("hello", "en")),
        ("Random Advice", get_random_advice()),
        ("Random Fact", get_random_fact()),
        ("Random Quote", get_random_quote()),
    ]
    for name, coro in tests:
        total += 1
        if await test_api(name, coro):
            passed += 1

    # 2. Real-Time APIs
    print("\n⚡ Real-Time Data APIs:")
    from tools.free_apis.free_realtime_apis import (
        get_weather_by_city, get_crypto_price, get_exchange_rate
    )
    tests = [
        ("Weather (Istanbul)", get_weather_by_city("istanbul")),
        ("Crypto (Bitcoin)", get_crypto_price("bitcoin", "usd")),
        ("Exchange Rate (USD)", get_exchange_rate("USD")),
    ]
    for name, coro in tests:
        total += 1
        if await test_api(name, coro):
            passed += 1

    # 3. Geo APIs
    print("\n🌍 Geolocation & Network APIs:")
    from tools.free_apis.free_geo_apis import (
        get_ip_geolocation, get_country_info, get_postal_code_info
    )
    tests = [
        ("IP Geolocation", get_ip_geolocation()),
        ("Country Info (Turkey)", get_country_info("turkey")),
        ("Postal Code (US/90210)", get_postal_code_info("us", "90210")),
    ]
    for name, coro in tests:
        total += 1
        if await test_api(name, coro):
            passed += 1

    # 4. Search APIs
    print("\n🔍 Search & Discovery APIs:")
    from tools.free_apis.free_search_apis import (
        ddg_instant_answer, search_academic_papers
    )
    tests = [
        ("DuckDuckGo (Python)", ddg_instant_answer("Python programming language")),
        ("Academic Search (AI)", search_academic_papers("artificial intelligence", 3)),
    ]
    for name, coro in tests:
        total += 1
        if await test_api(name, coro):
            passed += 1

    # 5. Tool Registration Check
    print("\n🔧 Tool Registration Check:")
    from tools import AVAILABLE_TOOLS
    free_tools = [
        "get_wikipedia_summary", "get_word_definition", "get_random_advice",
        "get_random_fact", "get_random_quote",
        "get_weather_by_city", "get_weather_openmeteo", "get_crypto_price", "get_exchange_rate",
        "get_ip_geolocation", "get_country_info", "get_postal_code_info",
        "ddg_instant_answer", "search_academic_papers",
    ]
    for tool_name in free_tools:
        total += 1
        registered = tool_name in AVAILABLE_TOOLS
        icon = "✅" if registered else "❌"
        print(f"  {icon} {tool_name} {'registered' if registered else 'MISSING'}")
        if registered:
            passed += 1

    # 6. Intent Parser Check
    print("\n🧠 Intent Parser Check:")
    from core.intent_parser import IntentParser
    parser = IntentParser()
    intent_tests = [
        ("bitcoin fiyatı nedir", "get_crypto_price"),
        ("dolar kuru", "get_exchange_rate"),
        ("istanbul hava durumu", "get_weather_by_city"),
        ("makale ara artificial intelligence", "search_academic_papers"),
    ]
    for text, expected_action in intent_tests:
        total += 1
        result = parser.parse(text)
        action = result.get("action", "")
        match = action == expected_action
        icon = "✅" if match else "⚠️"
        print(f"  {icon} \"{text}\" → {action} {'(expected: ' + expected_action + ')' if not match else ''}")
        if match:
            passed += 1

    # Summary
    print(f"\n{'='*50}")
    print(f"  Results: {passed}/{total} PASSED")
    print(f"{'='*50}")
    
    return 0 if passed >= total * 0.7 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
