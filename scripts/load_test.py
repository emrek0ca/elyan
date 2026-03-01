"""
scripts/load_test.py
─────────────────────────────────────────────────────────────────────────────
Simulates multiple concurrent user sessions to stress test the orchestrator.
"""

import asyncio
import time
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.multi_agent.orchestrator import AgentOrchestrator
from core.agent import Agent
from utils.logger import get_logger

logger = get_logger("load_test")

async def simulate_user(user_id: int, request: str):
    print(f"👤 User {user_id} starting request: {request[:40]}...")
    agent = Agent()
    orchestrator = AgentOrchestrator(agent)
    
    start_time = time.time()
    try:
        # simulate_request is usually called via gateway, but we test the logic layer here
        result = await orchestrator.manage_flow(None, request)
        duration = time.time() - start_time
        status = "✅ SUCCESS" if "✅" in result else "❌ FAILED"
        print(f"👤 User {user_id} finished: {status} in {duration:.2f}s")
        return True
    except Exception as e:
        print(f"👤 User {user_id} CRASHED: {e}")
        return False

async def run_load_test(concurrency: int = 3):
    print(f"🔥 Starting Load Test (Concurrency: {concurrency})")
    
    requests = [
        "Basit bir Python scripti yaz, ekrana 'Hello' bassın.",
        "Proje dizindeki README.md dosyasını oku.",
        "Hava durumu nasıl? (Hızlı bir araştırma simülasyonu)",
    ]
    
    tasks = []
    for i in range(concurrency):
        req = requests[i % len(requests)]
        tasks.append(simulate_user(i, req))
        
    start_total = time.time()
    results = await asyncio.gather(*tasks)
    total_duration = time.time() - start_total
    
    success_count = sum(1 for r in results if r)
    print(f"\n========================================")
    print(f"LOAD TEST COMPLETE")
    print(f"Total Duration: {total_duration:.2f}s")
    print(f"Success Rate: {success_count}/{concurrency}")
    print(f"========================================")

if __name__ == "__main__":
    conc = 3
    if len(sys.argv) > 1:
        conc = int(sys.argv[1])
    asyncio.run(run_load_test(conc))
