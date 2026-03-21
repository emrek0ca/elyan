from __future__ import annotations

import pytest

from elyan.sandbox import executor as sandbox_executor_module
from elyan.sandbox.executor import SandboxConfig, SandboxExecutor


@pytest.mark.asyncio
async def test_run_falls_back_to_legacy_when_docker_daemon_unavailable(monkeypatch):
    monkeypatch.setattr(sandbox_executor_module, "docker", None)
    sandbox = SandboxExecutor()
    monkeypatch.setattr(sandbox, "available", lambda: False)
    monkeypatch.setattr(sandbox_executor_module.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    called = {}

    async def fake_legacy(command, config, timeout):
        called["command"] = command
        return {
            "backend": "legacy-sandbox",
            "success": True,
            "stdout": "ok",
            "stderr": "",
            "return_code": 0,
            "sandboxed": True,
        }

    async def fake_cli(*args, **kwargs):
        raise AssertionError("docker cli path should not be used")

    monkeypatch.setattr(sandbox, "_run_legacy", fake_legacy)
    monkeypatch.setattr(sandbox, "_run_with_cli", fake_cli)

    result = await sandbox.run("echo ok", SandboxConfig(command="echo ok"), timeout=1)

    assert called["command"] == "echo ok"
    assert result["backend"] == "legacy-sandbox"
