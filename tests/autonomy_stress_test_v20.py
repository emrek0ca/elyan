import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.agent_loop import AgentLoop
from core.llm_client import LLMClient
from core.task_executor import TaskExecutor
from utils.logger import get_logger

logger = get_logger("tests.autonomy_stress")

async def run_stress_test():
    print("🚀 Starting Wiqo Autonomy Stress Test (v20.0)")
    
    # Initialize components
    llm = LLMClient()
    executor = TaskExecutor()
    loop = AgentLoop(llm, executor)
    
    # Complex Goal
    user_input = "Masaüstünde 10MB'dan büyük dosyaları bul, isimlerini bir not dosyasına yaz ve sonra o notun ekran görüntüsünü al."
    
    print(f"Goal: {user_input}")
    
    # Process the request
    # Since we don't want to actually run everything in a real environment (or do we?),
    # we can use a mock notify to see progress.
    
    async def mock_notify(msg):
        if isinstance(msg, dict) and msg.get("type") == "screenshot":
            print(f"📸 SCREENSHOT: {msg.get('path')}")
        else:
            print(f"ℹ️  [Wiqo]: {msg}")

    result = await loop.process(user_input, notify=mock_notify)
    
    print("\n--- FINAL RESULT ---")
    print(result)
    print("--------------------")

if __name__ == "__main__":
    asyncio.run(run_stress_test())
