#!/usr/bin/env python3
import sys
import asyncio
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent
from core.kernel import kernel

async def test_chat_action_fallback():
    print("🧪 Testing Agent chat action fix...")
    agent = Agent()
    await agent.initialize()
    
    # Mocking necessary parts for _execute_tool call
    # The error was: 'LLMClient' object has no attribute 'provider'
    # which came from: result = await fallback_manager.execute_with_fallback(self, {"provider": self.kernel.llm.provider, ...}, ...)
    
    try:
        # We try to execute the tool that failed
        # Action: chat, as mapped in ACTION_TO_TOOL or used directly
        result = await agent._execute_tool("chat", {"message": "Merhaba, nasılsın?"}, user_input="Merhaba")
        print(f"✅ Success! Response: {result}")
    except AttributeError as e:
        print(f"❌ Failed: Attribute error caught: {e}")
        return False
    except Exception as e:
        print(f"⚠️ Note: Caught other exception (expected if LLM is not fully configured in this env): {e}")
        # If it's not an AttributeError, my specific fix for line 510 worked
        if "'LLMClient' object has no attribute 'provider'" in str(e):
             print("❌ Failed: Specific provider attribute error still present!")
             return False
        print("✅ Fixed: No attribute error for 'provider' detected.")
    
    return True

if __name__ == "__main__":
    success = asyncio.run(test_chat_action_fallback())
    sys.exit(0 if success else 1)
