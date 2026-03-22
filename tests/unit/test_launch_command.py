from __future__ import annotations

from types import SimpleNamespace

from cli.commands import launch


def test_launch_starts_gateway_and_opens_dashboard(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(launch.gateway, "start_gateway", lambda daemon=False, port=None: calls.setdefault("start", (daemon, port)))
    monkeypatch.setattr(launch.gateway, "_fetch_gateway_status", lambda port: {"ok": True, "data": {"status": "online"}})
    monkeypatch.setattr(
        launch.dashboard,
        "open_dashboard",
        lambda port=None, no_browser=False, ops=False: calls.setdefault("dashboard", (port, no_browser, ops)),
    )

    code = launch.run(SimpleNamespace(port=18888, no_browser=True, ops=True))
    out = capsys.readouterr().out

    assert code == 0
    assert calls["start"] == (True, 18888)
    assert calls["dashboard"] == (18888, True, True)
    assert "Elyan launch başlıyor" in out
    assert "Elyan hazır" in out


def test_launch_stops_when_gateway_not_ready(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(launch.gateway, "start_gateway", lambda daemon=False, port=None: calls.setdefault("start", (daemon, port)))
    monkeypatch.setattr(launch.gateway, "_fetch_gateway_status", lambda port: {"ok": False, "error": "connection refused"})
    monkeypatch.setattr(launch.gateway, "_wait_until_gateway_ready", lambda port, timeout_s=4.0: False)
    monkeypatch.setattr(
        launch.dashboard,
        "open_dashboard",
        lambda port=None, no_browser=False, ops=False: calls.setdefault("dashboard", (port, no_browser, ops)),
    )

    code = launch.run(SimpleNamespace(port=18888, no_browser=False, ops=False))
    out = capsys.readouterr().out

    assert code == 1
    assert calls["start"] == (True, 18888)
    assert "dashboard" not in calls
    assert "Launch başarısız" in out
