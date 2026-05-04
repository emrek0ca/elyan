from __future__ import annotations

from types import SimpleNamespace

from cli.commands import launch


def test_launch_starts_gateway_without_opening_desktop_when_disabled(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(launch.gateway, "start_gateway", lambda daemon=False, port=None: calls.setdefault("start", (daemon, port)))
    monkeypatch.setattr(launch.gateway, "_fetch_gateway_status", lambda port: {"ok": True, "data": {"status": "online", "port": port}})
    monkeypatch.setattr(launch.gateway, "_wait_until_gateway_ready", lambda port, timeout_s=15.0: False)
    monkeypatch.setattr(
        launch.desktop,
        "open_desktop",
        lambda detached=False: calls.setdefault("desktop", detached) or 0,
    )

    code = launch.run(SimpleNamespace(port=18888, no_browser=True, ops=True, force=False))
    out = capsys.readouterr().out

    assert code == 0
    assert calls["start"] == (True, 18888)
    assert "desktop" not in calls
    assert "Elyan launch başlıyor" in out
    assert "Kurulumdan UI'ya" in out
    assert "bootstrap-owner -> login -> auth/me -> logout" in out
    assert "Ops console ürün UI değil." in out
    assert "Elyan hazır" in out


def test_launch_opens_desktop_when_enabled(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(launch.gateway, "start_gateway", lambda daemon=False, port=None: calls.setdefault("start", (daemon, port)))
    monkeypatch.setattr(launch.gateway, "_fetch_gateway_status", lambda port: {"ok": True, "data": {"status": "online", "port": port}})
    monkeypatch.setattr(launch.gateway, "_wait_until_gateway_ready", lambda port, timeout_s=15.0: False)
    monkeypatch.setattr(
        launch.desktop,
        "open_desktop",
        lambda detached=False: calls.setdefault("desktop", detached) or 0,
    )

    code = launch.run(SimpleNamespace(port=18888, no_browser=False, ops=False, force=False))
    out = capsys.readouterr().out

    assert code == 0
    assert calls["desktop"] is True
    assert "Kurulumdan UI'ya" in out
    assert "Elyan hazır" in out


def test_launch_stops_when_gateway_not_ready(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(launch.gateway, "start_gateway", lambda daemon=False, port=None: calls.setdefault("start", (daemon, port)))
    monkeypatch.setattr(launch.gateway, "_fetch_gateway_status", lambda port: {"ok": False, "error": "connection refused"})
    monkeypatch.setattr(launch.gateway, "_wait_until_gateway_ready", lambda port, timeout_s=15.0: False)
    monkeypatch.setattr(
        launch.desktop,
        "open_desktop",
        lambda detached=False: calls.setdefault("desktop", detached) or 0,
    )

    code = launch.run(SimpleNamespace(port=18888, no_browser=False, ops=False, force=False))
    out = capsys.readouterr().out

    assert code == 1
    assert calls["start"] == (True, 18888)
    assert "desktop" not in calls
    assert "Launch başarısız" in out
