from __future__ import annotations

from cli.commands import approve


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_pending_uses_v1_route_and_admin_token(monkeypatch, capsys):
    calls: dict[str, object] = {}

    monkeypatch.setenv("ELYAN_ADMIN_TOKEN", "token-123")

    def _fake_get(url, headers=None, timeout=0):
        calls["request"] = {"url": url, "headers": headers, "timeout": timeout}
        return _Response({"success": True, "approvals": [], "count": 0})

    monkeypatch.setattr(approve.requests, "get", _fake_get)

    approve.pending(output=None)
    out = capsys.readouterr().out

    request = calls["request"]
    assert request["url"].endswith("/api/v1/approvals/pending")
    assert request["headers"]["X-Elyan-Admin-Token"] == "token-123"
    assert "No pending approvals" in out


def test_approve_uses_v1_resolve_route_and_admin_token(monkeypatch, capsys):
    calls: dict[str, object] = {}

    monkeypatch.setenv("ELYAN_ADMIN_TOKEN", "token-456")

    def _fake_post(url, json=None, headers=None, timeout=0):
        calls["request"] = {
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        }
        return _Response({"success": True})

    monkeypatch.setattr(approve.requests, "post", _fake_post)

    approve.approve("req_123")
    out = capsys.readouterr().out

    request = calls["request"]
    assert request["url"].endswith("/api/v1/approvals/resolve")
    assert request["headers"]["X-Elyan-Admin-Token"] == "token-456"
    assert request["json"]["request_id"] == "req_123"
    assert "approved" in out
