#!/usr/bin/env python3
"""
Telegram approval flow harness.

Validates that approval_callback -> approval_query_callback resolves
pending approvals correctly (approve/deny/wrong-user).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from handlers import telegram_handler as th
from security.approval import ApprovalRequest, RiskLevel
from config.settings_manager import SettingsPanel


class DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, parse_mode=None):
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return SimpleNamespace(message_id=1)


class DummyApp:
    def __init__(self) -> None:
        self.bot = DummyBot()


class DummyCallbackQuery:
    def __init__(self, data: str, user_id: int) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.edits: list[str] = []
        self.answered: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answered.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text: str):
        self.edits.append(text)


class DummyUpdate:
    def __init__(self, query: DummyCallbackQuery) -> None:
        self.callback_query = query


def _make_request(user_id: int, request_id: str) -> ApprovalRequest:
    return ApprovalRequest(
        id=request_id,
        operation="shutdown_system",
        risk_level=RiskLevel.HIGH,
        description="Sistemi kapat",
        params={},
        user_id=user_id,
        timestamp="now",
    )


async def _wait_for_pending(request_id: str, timeout: float = 1.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if request_id in th.pending_approvals:
            return True
        await asyncio.sleep(0.01)
    return False


async def _run_case(decision: str) -> bool:
    user_id = 1234
    os.environ["ALLOWED_USER_IDS"] = str(user_id)

    th.telegram_app = DummyApp()
    th.pending_approvals.clear()
    th.pending_requests.clear()

    req = _make_request(user_id=user_id, request_id=f"req_{decision}_1")
    task = asyncio.create_task(th.approval_callback(req))

    if not await _wait_for_pending(req.id):
        print(f"FAIL: pending approval not registered for {decision}")
        return False

    query = DummyCallbackQuery(f"approval:{req.id}:{decision}", user_id=user_id)
    update = DummyUpdate(query)
    await th.approval_query_callback(update, None)

    result = await asyncio.wait_for(task, timeout=1.0)
    expected = decision == "approve"
    if bool(result) != expected:
        print(f"FAIL: approval result mismatch for {decision} (got {result})")
        return False

    if req.id in th.pending_approvals:
        print(f"FAIL: pending approval not cleared for {decision}")
        return False

    return True


async def _run_wrong_user_case() -> bool:
    user_id = 1234
    os.environ["ALLOWED_USER_IDS"] = str(user_id)

    th.telegram_app = DummyApp()
    th.pending_approvals.clear()
    th.pending_requests.clear()

    req = _make_request(user_id=user_id, request_id="req_wrong_user")
    task = asyncio.create_task(th.approval_callback(req))

    if not await _wait_for_pending(req.id):
        print("FAIL: pending approval not registered for wrong-user case")
        return False

    wrong_user = user_id + 1
    query = DummyCallbackQuery(f"approval:{req.id}:approve", user_id=wrong_user)
    update = DummyUpdate(query)
    await th.approval_query_callback(update, None)

    if task.done():
        print("FAIL: approval resolved by wrong user")
        return False

    th._resolve_pending_request(req.id, False)
    result = await asyncio.wait_for(task, timeout=1.0)
    if result is not False:
        print("FAIL: wrong-user case did not resolve to False")
        return False

    return True


async def _run() -> int:
    original_get = SettingsPanel.get

    def patched_get(self, key: str, default: Any = None) -> Any:
        if key == "allowed_user_ids":
            return []
        return original_get(self, key, default)

    SettingsPanel.get = patched_get
    try:
        ok = await _run_case("approve")
        ok = ok and await _run_case("deny")
        ok = ok and await _run_wrong_user_case()
        if ok:
            print("PASS: telegram approval harness ok")
            return 0
        return 1
    finally:
        SettingsPanel.get = original_get


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:
        print(f"FAIL: unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
