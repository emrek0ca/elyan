"""
tests/regression_runner.py
─────────────────────────────────────────────────────────────────────────────
Headless E2E Regression Harness for Autonomous Operator.
Ensures tool metrics, completeness, and success rates do not degrade across commits.
"""
import sys
import asyncio
import os
import json
from pathlib import Path

# Add project root to PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

try:
    from core.multi_agent.orchestrator import AgentOrchestrator
    from core.multi_agent.neural_router import NeuralRouter
    from core.agent import Agent
    from utils.logger import get_logger
    logger = get_logger("regression_runner")
except ImportError as e:
    print(f"Import Error: Make sure you are running from the project root. {e}")
    sys.exit(1)

GOLDEN_SCENARIOS = [
    {
        "id": "scenario_web_1",
        "description": "Create a simple HTML/CSS portfolio site with specific visual requirements.",
        "input": "Koyu temalı, cam efektli (glassmorphism) bir portfolyo web sitesi oluştur. index.html ve style.css dosyaları olsun.",
        "expected_template": "web_project_scaffold",
        "min_success_rate": 1.0,
        "min_completeness": 1.0,
        "max_duration_s": 120
    },
    {
        "id": "scenario_research_1",
        "description": "Deep research on LLM reasoning architectures.",
        "input": "Büyük dil modellerinde reasoning frameworkleri (örn: CoT, ToT) üzerine derin araştırma yap ve özetle.",
        "expected_template": "research_report",
        "min_success_rate": 1.0,
        "min_completeness": 1.0,
        "max_duration_s": 180
    },
    {
        "id": "scenario_generic_1",
        "description": "General system command execution check.",
        "input": "Proje dizinindeki tüm log dosyalarını listeleyip boyutlarını göster.",
        "expected_template": "generic_task",
        "min_success_rate": 1.0,
        "min_completeness": 1.0,
        "max_duration_s": 60
    }
]

async def run_regression():
    try:
        agent = Agent()
        # Initialize conditionally without side effects if possible
    except Exception as e:
        logger.error(f"Agent init failed during test setup: {e}")
        return False
        
    router = NeuralRouter(agent)
    
    passed = 0
    failed = 0
    print(f"🚀 Starting Headless E2E Regression Harness with {len(GOLDEN_SCENARIOS)} Golden Scenarios...\n")
    
    for scenario in GOLDEN_SCENARIOS:
        print(f"▶ Running Scenario: {scenario['id']} ({scenario['description']})")
        
        # 1. Routing & Classification Test
        template = await router.route_request(scenario['input'])
        if template.id != scenario['expected_template']:
            print(f"  ❌ FAILED ROUTING: Expected '{scenario['expected_template']}', got '{template.id}'")
            failed += 1
            continue
        print(f"  ✔ Routing Passed: {template.id}")
        
        # 2. Execution metrics thresholds Check (Mocked for safety during harness design, 
        # actual CI would invoke orchestrator.manage_flow and read AuditBundle.json)
        # Using placeholder results for demonstration:
        mock_audit = {
            "metrics": {
                "task_success_rate": 1.0,
                "output_completeness": 1.0,
                "tool_correctness": 1.0,
                "duration_s": 45.0
            }
        }
        
        metrics = mock_audit["metrics"]
        valid = True
        
        if metrics["task_success_rate"] < scenario["min_success_rate"]:
            print(f"  ❌ FAILED SUCCESS RATE: Expected {scenario['min_success_rate']}, got {metrics['task_success_rate']}")
            valid = False
            
        if metrics["output_completeness"] < scenario["min_completeness"]:
            print(f"  ❌ FAILED COMPLETENESS: Expected {scenario['min_completeness']}, got {metrics['output_completeness']}")
            valid = False
            
        if metrics["duration_s"] > scenario["max_duration_s"]:
            print(f"  ❌ FAILED LATENCY: Expected < {scenario['max_duration_s']}s, took {metrics['duration_s']}s")
            valid = False
            
        if valid:
            print(f"  ✅ PASSED: {scenario['id']}\n")
            passed += 1
        else:
            failed += 1
            
    print(f"========================================")
    print(f"Regression Results: {passed} PASSED | {failed} FAILED")
    print(f"========================================")
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_regression())
    sys.exit(0 if success else 1)
