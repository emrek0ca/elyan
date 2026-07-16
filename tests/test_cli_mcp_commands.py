"""`elyan mcp` komut sözleşmeleri — MCP büyüme kanalının yönetim yüzeyi."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from runtime import state_store


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def test_mcp_add_list_disable_remove_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _isolate(monkeypatch, tmp_path)
    from cli.main import cmd_mcp

    # add
    add_args = argparse.Namespace(
        mcp_action="add",
        name="dosya",
        command="npx",
        args=["-y,@modelcontextprotocol/server-filesystem,/tmp"],
        cwd="",
    )
    assert cmd_mcp(add_args) == 0
    out = capsys.readouterr().out
    assert "Eklendi:" in out

    servers = state_store.snapshot()["skills"]["mcpServers"]
    assert len(servers) == 1
    server_id = servers[0]["id"]
    assert servers[0]["command"] == "npx"
    assert servers[0]["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    # list
    assert cmd_mcp(argparse.Namespace(mcp_action="list")) == 0
    assert "dosya" in capsys.readouterr().out

    # disable → enable
    assert cmd_mcp(argparse.Namespace(mcp_action="disable", server_id=server_id)) == 0
    assert state_store.snapshot()["skills"]["mcpServers"][0]["enabled"] is False
    assert cmd_mcp(argparse.Namespace(mcp_action="enable", server_id=server_id)) == 0
    assert state_store.snapshot()["skills"]["mcpServers"][0]["enabled"] is True

    # remove
    assert cmd_mcp(argparse.Namespace(mcp_action="remove", server_id=server_id)) == 0
    assert state_store.snapshot()["skills"]["mcpServers"] == []
    # olmayan id → hata kodu
    assert cmd_mcp(argparse.Namespace(mcp_action="remove", server_id="yok")) == 1


def test_curated_app_commands_use_oauth_without_manual_urls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from cli import main as cli_main

    calls: list[tuple[str, dict[str, object]]] = []

    class FakeBridge:
        def handle(self, request: dict[str, object]) -> dict[str, object]:
            capability = str(request.get("capability", ""))
            payload = request.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            calls.append((capability, payload))
            data: dict[str, object]
            if capability == "backend.integrations.apps":
                data = {
                    "apps": [
                        {
                            "id": "gmail",
                            "displayName": "Gmail",
                            "available": True,
                            "connected": False,
                        }
                    ]
                }
            elif capability == "backend.integrations.oauth_start":
                data = {"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?state=safe"}
            else:
                data = {"connected": False}
            return {
                "ok": True,
                "result": {
                    "ok": True,
                    "result": {"ok": True, "statusCode": 200, "data": data},
                },
            }

    opened: list[str] = []
    fake_bridge = FakeBridge()
    monkeypatch.setattr(cli_main, "_bridge", lambda: fake_bridge)
    monkeypatch.setattr(
        cli_main.webbrowser,
        "open",
        lambda url, new=0: opened.append(url) or True,
    )

    assert cli_main.cmd_apps(argparse.Namespace()) == 0
    assert "gmail" in capsys.readouterr().out
    assert cli_main.cmd_connect(argparse.Namespace(app_id="gmail")) == 0
    assert opened == ["https://accounts.google.com/o/oauth2/v2/auth?state=safe"]
    assert cli_main.cmd_disconnect(argparse.Namespace(app_id="gmail")) == 0
    assert calls == [
        ("backend.integrations.apps", {}),
        ("backend.integrations.oauth_start", {"appId": "gmail"}),
        ("backend.integrations.disconnect", {"appId": "gmail", "_confirmed": True}),
    ]


@pytest.mark.parametrize(
    "auth_url",
    [
        "http://accounts.google.com/o/oauth2/v2/auth?state=safe",
        "https://evil.example/o/oauth2/v2/auth?state=safe",
        "https://accounts.google.com.evil.example/o/oauth2/v2/auth?state=safe",
        "https://user@accounts.google.com/o/oauth2/v2/auth?state=safe",
        "https://accounts.google.com:444/o/oauth2/v2/auth?state=safe",
        "https://accounts.google.com/o/oauth2/v2/auth?state=safe#fragment",
        "https://linear.app/oauth/authorize?state=safe",
    ],
)
def test_connect_rejects_untrusted_oauth_url_without_opening_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    auth_url: str,
) -> None:
    from cli import main as cli_main

    class FakeBridge:
        def handle(self, _request: dict[str, object]) -> dict[str, object]:
            return {
                "ok": True,
                "result": {
                    "ok": True,
                    "result": {
                        "ok": True,
                        "statusCode": 200,
                        "data": {"authUrl": auth_url},
                    },
                },
            }

    opened: list[str] = []
    monkeypatch.setattr(cli_main, "_bridge", lambda: FakeBridge())
    monkeypatch.setattr(cli_main.webbrowser, "open", lambda url, new=0: opened.append(url) or True)

    assert cli_main.cmd_connect(argparse.Namespace(app_id="gmail")) == 1
    assert opened == []
    assert "güvenlik doğrulamasından geçmedi" in capsys.readouterr().out
