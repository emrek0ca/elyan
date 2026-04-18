from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.agents.code_scout import CodeScoutAgent
from core.agents.message_bus import get_agent_bus
from core.agents.orchestrator import DevAgentOrchestrator
from core.multi_agent.message_bus import get_message_bus
from core.sandbox.docker_runtime import NetworkPolicy, SandboxRuntime
from core.skills.plugins.base_plugin import PluginManifest, SkillPlugin


class _ExamplePlugin(SkillPlugin):
    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            name="example",
            version="1.0.0",
            description="Example plugin",
            required_permissions=["read"],
        )

    async def execute(self, context: dict) -> dict:
        return {"ok": True, "context": dict(context)}

    def health_check(self) -> bool:
        return True


def test_message_bus_wrapper_uses_canonical_singleton() -> None:
    assert get_agent_bus() is get_message_bus()


def test_plugin_base_supports_concrete_implementations() -> None:
    plugin = _ExamplePlugin()

    assert plugin.health_check() is True
    assert plugin.get_manifest().sandbox_required is True
    assert asyncio.run(plugin.execute({"task": "hello"})) == {"ok": True, "context": {"task": "hello"}}


def test_code_scout_scans_workspace_for_matches(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("from core.decision_fabric import DecisionFabric\n")
    (workspace / "README.md").write_text("Iyzico checkout flow\n")

    scout = CodeScoutAgent()
    report = scout.scan(workspace, query="decision fabric", limit=10)

    assert report["workspace"] == str(workspace)
    assert report["matches"] >= 1
    assert any(item["path"].endswith("app.py") for item in report["findings"])
    assert report["language_breakdown"]["python"] == 1


def test_orchestrator_creates_multistep_plan() -> None:
    orchestrator = DevAgentOrchestrator()
    plan = orchestrator.build_plan("Fix auth bug and verify login flow")

    assert len(plan) >= 3
    assert plan[0].kind == "scout"
    assert any(step.kind == "verify" for step in plan)


def test_sandbox_runtime_enforces_safe_defaults_and_local_workspace(tmp_path: Path) -> None:
    runtime = SandboxRuntime()
    try:
        runtime.stage_workspace(tmp_path)
        runtime.write_file("notes/checklist.txt", "hello")

        assert runtime.read_file("notes/checklist.txt") == "hello"
        assert runtime.default_limits.cpus == "2.0"
        assert runtime.default_limits.memory == "2g"
        assert runtime.default_limits.timeout == 60

        with pytest.raises(ValueError):
            runtime.write_file("../escape.txt", "nope")
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_sandbox_runtime_execute_code_uses_docker_safe_settings(monkeypatch, tmp_path: Path) -> None:
    runtime = SandboxRuntime()
    runtime.stage_workspace(tmp_path)

    calls: dict[str, object] = {}

    async def _fake_execute(**kwargs):
        calls.update(kwargs)
        return {"success": True, "returncode": 0, "sandboxed": True}

    monkeypatch.setattr(runtime._docker, "execute", _fake_execute)
    try:
        result = await runtime.execute_code("print('hello')", language="python", timeout=240)
    finally:
        runtime.close()

    assert result["success"] is True
    assert calls["network"] == NetworkPolicy.NONE
    assert calls["limits"].cpus == "2.0"
    assert calls["limits"].memory == "2g"
    assert calls["limits"].timeout == 240
    assert str(calls["workspace_dir"]).startswith(str(runtime.workspace_root))
