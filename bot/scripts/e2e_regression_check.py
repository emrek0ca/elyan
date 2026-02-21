#!/usr/bin/env python3
"""
Lightweight end-to-end regression check for intent -> task -> execution flow.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.intent_parser import IntentParser
from core.task_engine import TaskEngine, TaskDefinition


async def _run_checks() -> int:
    parser = IntentParser()
    engine = TaskEngine()

    # 1) Intent regression: power command must resolve to shutdown action.
    power_intent = parser.parse("bilgisayarı kapat")
    if not power_intent or power_intent.get("action") != "shutdown_system":
        print("FAIL: 'bilgisayarı kapat' intent route invalid")
        return 1

    # 2) Approval regression: denied approval must block execution.
    class DenyApproval:
        async def request_approval(self, **kwargs):
            return {"approved": False, "reason": "manual deny"}

    class DummyExecutor:
        async def execute(self, tool_func, params):
            return await tool_func(**params)

    engine.approval = DenyApproval()
    engine.executor = DummyExecutor()

    result = await engine._execute_tasks(
        [
            TaskDefinition(
                id="task_1",
                action="shutdown_system",
                params={},
                description="Sistemi kapat",
                requires_approval=True,
            )
        ],
        notify_callback=None,
        user_id="1",
    )
    if result.get("success") is True:
        print("FAIL: shutdown_system executed without approval")
        return 1

    print("PASS: intent and approval regression checks are healthy")
    return 0


def main() -> int:
    try:
        return asyncio.run(_run_checks())
    except Exception as exc:
        print(f"FAIL: unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
