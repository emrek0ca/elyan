import asyncio

from handlers import telegram_handler as tg


class _Risk:
    def __init__(self, value: str):
        self.value = value


class _Request:
    def __init__(self, request_id: str, user_id: int):
        self.id = request_id
        self.user_id = user_id
        self.operation = "shutdown_system"
        self.description = "Bilgisayarı kapatma komutu"
        self.risk_level = _Risk("critical")


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return True


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


def test_approval_callback_returns_none_without_telegram_user_id():
    original_app = tg.telegram_app
    tg.telegram_app = _FakeApp()
    try:
        req = _Request("req_local", 0)
        approved = asyncio.run(tg.approval_callback(req))
    finally:
        tg.telegram_app = original_app
        tg.pending_approvals.clear()
        tg.pending_requests.clear()

    assert approved is None


def test_approval_callback_waits_and_returns_decision():
    original_app = tg.telegram_app
    tg.telegram_app = _FakeApp()
    try:
        req = _Request("req_tg_1", 123456)

        async def scenario():
            wait_task = asyncio.create_task(tg.approval_callback(req))
            # Let callback register pending request.
            await asyncio.sleep(0)

            pending = tg.pending_approvals.get(req.id)
            assert pending is not None
            pending["future"].set_result(True)
            return await wait_task

        approved = asyncio.run(scenario())
    finally:
        tg.telegram_app = original_app
        tg.pending_approvals.clear()
        tg.pending_requests.clear()

    assert approved is True

