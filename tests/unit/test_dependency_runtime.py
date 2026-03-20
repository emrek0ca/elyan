from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.dependencies import DependencyInstallRecord, PackageRuntimeResolver
from core.dependencies import runtime as dependency_runtime
from core.skills import tool_runtime
import tools


def _patch_runtime_config(monkeypatch, tmp_path):
    audit_path = tmp_path / "dependency_runtime.jsonl"
    state_path = tmp_path / "dependency_runtime_state.json"
    venv_root = tmp_path / "venvs"
    config_map = {
        "dependency_runtime.enabled": True,
        "dependency_runtime.mode": "managed_venv",
        "dependency_runtime.managed_venv_root": str(venv_root),
        "dependency_runtime.auto_install": True,
        "dependency_runtime.auto_retry": True,
        "dependency_runtime.trusted_sources": ["pypi", "marketplace"],
        "dependency_runtime.blocked_schemes": ["git+", "http://", "https://", "file:", "ssh://", "hg+", "svn+"],
        "dependency_runtime.audit_path": str(audit_path),
        "dependency_runtime.state_path": str(state_path),
    }

    def fake_get(key, default=None):
        return config_map.get(key, default)

    monkeypatch.setattr(dependency_runtime.elyan_config, "get", fake_get)
    return config_map


def test_dependency_runtime_blocks_untrusted_direct_source(tmp_path, monkeypatch):
    _patch_runtime_config(monkeypatch, tmp_path)
    runtime = PackageRuntimeResolver()
    monkeypatch.setattr(runtime, "_is_spec_available", lambda spec: False)

    record = runtime.ensure_module(
        "playwright",
        install_spec="git+https://example.com/skills/playwright.git",
        source="marketplace",
        trust_level="trusted",
        allow_install=True,
    )

    assert record.status == "blocked"
    assert record.reason == "untrusted_or_direct_source"
    snapshot = runtime.snapshot()
    assert snapshot["blocked_packages"]
    assert snapshot["blocked_packages"][0]["package"] == "playwright"


def test_dependency_runtime_persists_state_and_reports_installing(tmp_path, monkeypatch):
    _patch_runtime_config(monkeypatch, tmp_path)
    runtime = PackageRuntimeResolver()
    available = {"value": False}
    observed = {"installing_seen": False}

    monkeypatch.setattr(runtime, "_ensure_managed_venv", lambda: None)
    monkeypatch.setattr(runtime, "_ensure_site_paths", lambda: None)
    monkeypatch.setattr(runtime, "_reload_modules", lambda spec: None)
    monkeypatch.setattr(runtime, "_is_spec_available", lambda spec: available["value"])

    def fake_run_installer(spec):
        observed["installing_seen"] = bool(runtime.snapshot().get("installing_packages"))
        available["value"] = True
        return True, "installed", "pip"

    monkeypatch.setattr(runtime, "_run_installer", fake_run_installer)
    monkeypatch.setattr(runtime, "_run_post_install", lambda spec: (True, ""))

    record = runtime.ensure_module(
        "fakepkg",
        install_spec="fakepkg",
        source="pypi",
        trust_level="trusted",
        allow_install=True,
    )

    assert observed["installing_seen"] is True
    assert record.status == "installed"
    assert record.installed is True
    assert runtime.state_path.exists()
    assert runtime.snapshot()["installed_packages"]

    second_runtime = PackageRuntimeResolver()
    second_snapshot = second_runtime.snapshot()
    assert second_snapshot["installed_packages"]
    assert second_snapshot["installed_packages"][0]["package"] == "fakepkg"


@pytest.mark.asyncio
async def test_execute_registered_tool_retries_after_missing_dependency(monkeypatch):
    fake_runtime = SimpleNamespace()
    fake_runtime.calls = []

    async def ensure_skill_async(*args, **kwargs):
        fake_runtime.calls.append(("skill", args, kwargs))
        return []

    async def ensure_tool_async(*args, **kwargs):
        fake_runtime.calls.append(("tool", args, kwargs))
        return []

    async def ensure_from_error_async(error_text, **kwargs):
        fake_runtime.calls.append(("error", error_text, kwargs))
        return [SimpleNamespace(to_dict=lambda: {"status": "installed", "package": "bs4"})]

    fake_runtime.ensure_skill_async = ensure_skill_async
    fake_runtime.ensure_tool_async = ensure_tool_async
    fake_runtime.ensure_from_error_async = ensure_from_error_async

    monkeypatch.setattr(tool_runtime, "get_dependency_runtime", lambda: fake_runtime)
    monkeypatch.setattr(tool_runtime.skill_manager, "manifest_from_skill", lambda _name: {"python_dependencies": []})

    async def fake_tool():
        return {"success": True, "message": "ok"}

    original = tools._loaded_tools.get("scrape_page")
    tools._loaded_tools["scrape_page"] = fake_tool

    call_count = {"n": 0}

    async def fake_execute(self, tool_func, params):
        _ = (tool_func, params)
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"success": False, "error": "No module named 'bs4'"}
        return {"success": True, "status": "success", "message": "recovered"}

    monkeypatch.setattr(tool_runtime.TaskExecutor, "execute", fake_execute)

    try:
        result = await tool_runtime.execute_registered_tool("scrape_page", {}, skill_name="")
    finally:
        if original is None:
            tools._loaded_tools.pop("scrape_page", None)
        else:
            tools._loaded_tools["scrape_page"] = original

    assert call_count["n"] == 2
    assert result["success"] is True
    assert result["message"] == "recovered"
    assert result["dependency_runtime"]["auto_retry"] is True
    assert any(call[0] == "error" for call in fake_runtime.calls)


def test_dependency_runtime_snapshot_exposes_installing_state(tmp_path, monkeypatch):
    _patch_runtime_config(monkeypatch, tmp_path)
    runtime = PackageRuntimeResolver()
    runtime._update_state(
        DependencyInstallRecord(
            package="demo",
            modules=["demo"],
            install_spec="demo",
            source="pypi",
            trust_level="trusted",
            status="installing",
            reason="install_started",
            retryable=True,
            installed=False,
            started_at="2026-03-20T00:00:00Z",
            finished_at="",
            duration_ms=0,
            attempts=1,
            venv_path=str(tmp_path / "venv"),
            python_path=str(tmp_path / "venv" / "bin" / "python"),
        )
    )

    snapshot = runtime.snapshot()
    assert snapshot["status_counts"]["installing"] == 1
    assert snapshot["installing_packages"][0]["package"] == "demo"
