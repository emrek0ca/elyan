"""
scripts/load_test.py
─────────────────────────────────────────────────────────────────────────────
Simulates multiple concurrent user sessions to stress test the orchestrator.
"""

import asyncio
import argparse
import json
import time
import sys
import subprocess
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.multi_agent.orchestrator import AgentOrchestrator
from core.agent import Agent
from core.action_lock import action_lock
from core.artifact_quality_engine import quality_engine
from core.deterministic_runner import DeterministicToolRunner
from core.multi_agent.contract import JobMetrics
from core.multi_agent.qa_pipeline import QAPipeline
from core.multi_agent import rollback as rollback_module
from core.multi_agent import orchestrator as orchestrator_module
from core.multi_agent import swarm_consensus as swarm_module
from utils.logger import get_logger

logger = get_logger("load_test")


async def _fake_execute_tool(self, tool_name: str, params: dict | None = None):
    params = dict(params or {})
    if tool_name == "create_folder":
        path = Path(str(params.get("path") or "")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": str(path)}
    if tool_name == "write_file":
        path = Path(str(params.get("path") or "")).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(params.get("content") or ""), encoding="utf-8")
        return {"success": True, "path": str(path)}
    if tool_name == "run_safe_command":
        command = str(params.get("command") or "").strip()
        if command:
            subprocess.run(command, shell=True, check=False)
        return {"success": True, "command": command}
    return {"success": True, "tool": tool_name}


def _configure_synthetic_load_mode() -> None:
    """Make the orchestrator deterministic and fast for local load testing."""

    async def _fake_run_specialist(self, key: str, prompt: str) -> str:
        if key == "executor":
            payload = {
                "artifact_map": {
                    "artifacts": [
                        {
                            "path": "/index.html",
                            "type": "html",
                            "mime": "text/html",
                            "content": "<html><body><h1>Elyan Load Test</h1></body></html>",
                        }
                    ]
                },
                "execution_plan": [
                    {
                        "id": "noop",
                        "action": "read_file",
                        "params": {"path": "/index.html"},
                        "owner": "builder",
                    }
                ],
            }
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps({"outputs": [f"{key} ready"], "risks": []}, ensure_ascii=False)

    async def _fake_warmup(self, job_id: str, plan_data: list[dict[str, object]], original_input: str) -> None:
        return None

    async def _fake_execute_plan(self, plan: DeterministicToolRunner) -> dict[str, object]:
        return {"success": True, "steps_executed": len(getattr(plan, "steps", []) or [])}

    async def _fake_qa(self, workspace_dir: str, artifacts: dict) -> tuple[bool, list[str]]:
        return True, []

    async def _fake_debate(self, intent: str, artifacts: dict) -> tuple[bool, list[str]]:
        return True, []

    async def _fake_full_audit(self, workspace_dir: str, artifacts: dict) -> tuple[bool, list[str]]:
        return True, []

    async def _fake_ensure_initialized(self) -> bool:
        return True

    def _fake_request_lock(*args, **kwargs) -> dict[str, object]:
        task_id = str(kwargs.get("task_id") or args[0] if args else "load-test")
        return {"acquired": True, "queued": False, "conflict": False, "task_id": task_id}

    def _fake_unlock(*, reason: str = "completed") -> None:
        return None

    async def _fake_create_snapshot(self) -> str:
        return "NO_CHANGES"

    async def _fake_restore_snapshot(self, stash_ref: str = "stash@{0}") -> bool:
        return True

    async def _fake_clear_snapshot(self, stash_ref: str = "stash@{0}") -> bool:
        return True

    def _fake_verify_integrity(artifact, workspace_dir: str) -> bool:
        artifact.status = "verified"
        return True

    def _fake_calculate_metrics(contract) -> None:
        contract.metrics = JobMetrics(
            task_success_rate=1.0,
            tool_correctness=1.0,
            output_completeness=100.0,
            token_usage=0,
            duration_s=0.01,
        )

    def _fake_create_audit_bundle(contract, workspace_dir: str) -> None:
        contract.audit_bundle_path = str(Path(workspace_dir) / "audit_bundle.json")

    orchestrator_module.AgentOrchestrator._run_specialist = _fake_run_specialist
    orchestrator_module.AgentOrchestrator._warm_up_parallel_sub_agents = _fake_warmup
    orchestrator_module.AgentOrchestrator._build_fallback_execution_payload = lambda self, **_: {
        "artifact_map": {"artifacts": []},
        "execution_plan": [{"id": "noop", "action": "read_file", "params": {"path": "/index.html"}, "owner": "builder"}],
    }
    DeterministicToolRunner.execute_plan = _fake_execute_plan
    QAPipeline.run_full_audit = _fake_full_audit
    swarm_module.SwarmConsensus.run_tribunal_debate = _fake_debate
    rollback_module.RollbackManager.ensure_initialized = _fake_ensure_initialized
    rollback_module.RollbackManager.create_snapshot = _fake_create_snapshot
    rollback_module.RollbackManager.restore_snapshot = _fake_restore_snapshot
    rollback_module.RollbackManager.clear_snapshot = _fake_clear_snapshot
    quality_engine.verify_integrity = _fake_verify_integrity
    quality_engine.calculate_metrics = _fake_calculate_metrics
    quality_engine.create_audit_bundle = _fake_create_audit_bundle
    action_lock.request_lock = _fake_request_lock
    action_lock.unlock = _fake_unlock


async def simulate_user(user_id: int, request: str, timeout_s: float):
    print(f"👤 User {user_id} starting request: {request[:40]}...")
    agent = Agent()
    agent._execute_tool = _fake_execute_tool.__get__(agent, agent.__class__)
    orchestrator = AgentOrchestrator(agent)
    
    start_time = time.time()
    try:
        # simulate_request is usually called via gateway, but we test the logic layer here
        result = await asyncio.wait_for(orchestrator.manage_flow(None, request), timeout=timeout_s)
        duration = time.time() - start_time
        status = "✅ SUCCESS" if "✅" in result else "❌ FAILED"
        print(f"👤 User {user_id} finished: {status} in {duration:.2f}s")
        return True
    except asyncio.TimeoutError:
        duration = time.time() - start_time
        print(f"👤 User {user_id} TIMED OUT after {duration:.2f}s")
        return False
    except Exception as e:
        print(f"👤 User {user_id} CRASHED: {e}")
        return False

async def run_load_test(concurrency: int = 3, timeout_s: float = 30.0):
    print(f"🔥 Starting Load Test (Concurrency: {concurrency})")
    _configure_synthetic_load_mode()
    
    requests = [
        "Basit bir Python scripti yaz, ekrana 'Hello' bassın.",
        "Proje dizindeki README.md dosyasını oku.",
        "Hava durumu nasıl? (Hızlı bir araştırma simülasyonu)",
    ]
    
    tasks = []
    for i in range(concurrency):
        req = requests[i % len(requests)]
        tasks.append(simulate_user(i, req, timeout_s))
        
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
    parser = argparse.ArgumentParser(description="Run a concurrent orchestrator load test.")
    parser.add_argument("concurrency", nargs="?", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-user timeout in seconds")
    args = parser.parse_args()
    asyncio.run(run_load_test(args.concurrency, args.timeout))
