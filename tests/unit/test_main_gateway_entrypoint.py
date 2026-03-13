"""Regression tests for root main gateway entrypoint behavior."""

from __future__ import annotations

import types

import main as app_main


def test_run_gateway_passes_requested_port_to_server_start(monkeypatch):
    calls: dict[str, object] = {}

    class _FakeAgent:
        def initialize(self):
            calls["agent_initialized"] = True
            return True

    class _FakeServer:
        def __init__(self, agent):
            calls["server_agent"] = agent

        def start(self, host="127.0.0.1", port=18789):
            calls["start_port"] = port
            calls["start_host"] = host
            return "started"

        def stop(self):
            calls["stopped"] = True
            return "stopped"

    class _FakeLoop:
        def run_until_complete(self, value):
            return value

        def run_forever(self):
            raise KeyboardInterrupt()

        def close(self):
            calls["loop_closed"] = True

    fake_agent_mod = types.SimpleNamespace(Agent=_FakeAgent)
    fake_server_mod = types.SimpleNamespace(ElyanGatewayServer=_FakeServer)
    fake_asyncio_mod = types.SimpleNamespace(
        new_event_loop=lambda: _FakeLoop(),
        set_event_loop=lambda loop: None,
    )
    monkeypatch.setitem(app_main.sys.modules, "core.agent", fake_agent_mod)
    monkeypatch.setitem(app_main.sys.modules, "core.gateway.server", fake_server_mod)
    monkeypatch.setitem(app_main.sys.modules, "asyncio", fake_asyncio_mod)
    monkeypatch.setattr(app_main, "_load_dotenv", lambda: None)
    monkeypatch.setattr(app_main.click, "echo", lambda *args, **kwargs: None)

    app_main._run_gateway(18889)

    assert calls.get("agent_initialized") is True
    assert calls.get("start_port") == 18889
    assert calls.get("start_host") == "127.0.0.1"
    assert calls.get("stopped") is True
    assert calls.get("loop_closed") is True
