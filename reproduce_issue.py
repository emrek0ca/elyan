import asyncio
import sys
import os
import time
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))

from core.agent import Agent
from core.kernel import kernel
from utils.logger import get_logger

async def test_elyan():
    print("🚀 Elyan Testi Başlatılıyor...")
    
    # Initialize Kernel and Agent
    agent = Agent()
    await agent.initialize()
    
    # Test cases
    test_inputs = [
        "Selam, sen kimsin?",
        "Masaüstüne 'test_elyan.txt' adında bir dosya oluştur ve içine 'Merhaba Dünya' yaz.",
    ]
    
    for inp in test_inputs:
        print(f"\n--- Kullanıcı: {inp} ---")
        try:
            response = await agent.process(inp)
            print(f"--- Elyan: {response} ---")
        except Exception as e:
            print(f"❌ Hata: {e}")

if __name__ == "__main__":
    asyncio.run(test_elyan())
