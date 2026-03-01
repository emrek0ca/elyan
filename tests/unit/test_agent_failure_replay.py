import pytest
from unittest.mock import AsyncMock, patch

from core.agent import Agent


@pytest.mark.asyncio
async def test_failure_replay_runs_latest_filesystem_task_spec():
    agent = Agent()
    intent = {"action": "failure_replay", "params": {"limit": 5}}
    task_spec = {
        "intent": "filesystem_batch",
        "version": "1.1",
        "goal": "fs replay",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 10, "run_timeout_s": 60},
        "retries": {"max_attempts": 1},
        "steps": [{"id": "s1", "action": "write_file", "path": "~/Desktop/not.md", "content": "abc"}],
    }
    failed_payload = {"user_input": "not.md yaz", "task_spec": task_spec, "_run_dir": "/tmp/run1"}

    with patch("core.agent.RunStore.find_latest_failed_task", return_value=failed_payload):
        with patch.object(agent, "_validate_filesystem_task_spec", return_value=True):
            with patch.object(agent, "_run_filesystem_task_spec", AsyncMock(return_value="Replay OK")):
                out = await agent._run_direct_intent(intent, "son başarısız görevi tekrar dene", "inference", [], user_id="u1")
                assert out == "Replay OK"

