import asyncio
import os
from core.agent_loop import AgentLoop
from core.llm_client import LLMClient
from core.task_executor import TaskExecutor
from core.agent import ACTION_TO_TOOL

async def verify_infrastructure():
    print("--- 1. Tool Mapping Verification ---")
    essential_mappings = ["mkdir", "create_directory", "list_files", "open_app"]
    for mapping in essential_mappings:
        tool = ACTION_TO_TOOL.get(mapping)
        if tool:
            print(f"✅ {mapping} -> {tool}")
        else:
            print(f"❌ {mapping} is MISSING!")

    print("\n--- 2. Intent Gating Verification ---")
    llm = LLMClient()
    executor = TaskExecutor()
    loop = AgentLoop(llm, executor)
    
    test_cases = [
        ("Naber?", "CHAT"),
        ("Selam Elyan", "CHAT"),
        ("Masaüstünü listele", "ACTION"),
        ("Yeni bir klasör oluştur", "ACTION"),
        ("SS al", "ACTION")
    ]
    
    for text, expected in test_cases:
        intent_type, _ = await loop._gate_intent(text)
        if intent_type == expected:
            print(f"✅ '{text}' -> {intent_type}")
        else:
            print(f"❌ '{text}' -> {intent_type} (Expected: {expected})")

    print("\n--- 3. Config Read-Only Verification ---")
    from config.settings_manager import SettingsPanel
    panel = SettingsPanel()

    provider = panel.get("llm_provider", "unknown")
    fallback_mode = panel.get("llm_fallback_mode", "aggressive")
    fallback_order = panel.get("llm_fallback_order", [])
    assistant_style = panel.get("assistant_style", "professional_friendly_short")

    print(f"Configured provider: {provider}")
    print(f"Fallback mode: {fallback_mode}")
    print(f"Fallback order: {fallback_order}")
    print(f"Assistant style: {assistant_style}")

    env_path = os.path.join(os.getcwd(), ".env")
    with open(env_path, "r") as f:
        content = f.read()
        if "LLM_TYPE=" in content:
            print("✅ .env contains LLM_TYPE")
        else:
            print("❌ .env does not contain LLM_TYPE")

if __name__ == "__main__":
    asyncio.run(verify_infrastructure())
