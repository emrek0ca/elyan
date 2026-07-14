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
