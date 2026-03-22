from pathlib import Path

import pytest

import tools
from core.skills.manager import SkillManager


def _mock_config(monkeypatch):
    store = {"skills.enabled": []}

    def _get(key, default=None):
        return store.get(key, default)

    def _set(key, value):
        store[key] = value

    monkeypatch.setattr("core.skills.manager.elyan_config.get", _get)
    monkeypatch.setattr("core.skills.manager.elyan_config.set", _set)
    return store


def test_install_builtin_skill_enables_and_persists(tmp_path: Path, monkeypatch):
    _mock_config(monkeypatch)
    mgr = SkillManager()
    mgr.skills_dir = tmp_path
    mgr.skills_dir.mkdir(parents=True, exist_ok=True)

    ok, msg, info = mgr.install_skill("research")
    assert ok is True
    assert "yüklendi" in msg
    assert info is not None
    assert info["installed"] is True
    assert info["enabled"] is True
    assert (tmp_path / "research" / "skill.json").exists()


def test_disable_skill_updates_enabled_set(tmp_path: Path, monkeypatch):
    store = _mock_config(monkeypatch)
    mgr = SkillManager()
    mgr.skills_dir = tmp_path
    mgr.skills_dir.mkdir(parents=True, exist_ok=True)
    mgr.install_skill("files")

    ok, msg, info = mgr.set_enabled("files", False)
    assert ok is True
    assert "devre dışı" in msg
    assert info is not None
    assert info["enabled"] is False
    assert "files" not in set(store.get("skills.enabled", []))


def test_edit_skill_updates_manifest_and_enabled_state(tmp_path: Path, monkeypatch):
    store = _mock_config(monkeypatch)
    mgr = SkillManager()
    mgr.skills_dir = tmp_path
    mgr.skills_dir.mkdir(parents=True, exist_ok=True)
    mgr.install_skill("files")

    ok, msg, info = mgr.edit_skill(
        "files",
        {
            "description": "Yeni açıklama",
            "approval_level": 2,
            "enabled": False,
            "required_tools": ["write_file"],
        },
    )

    assert ok is True
    assert "güncellendi" in msg
    assert info is not None
    assert info["description"] == "Yeni açıklama"
    assert info["approval_level"] == 2
    assert info["required_tools"] == ["write_file"]
    assert info["enabled"] is False
    assert "files" not in set(store.get("skills.enabled", []))


def test_check_reports_missing_tools(tmp_path: Path, monkeypatch):
    _mock_config(monkeypatch)
    mgr = SkillManager()
    mgr.skills_dir = tmp_path
    mgr.skills_dir.mkdir(parents=True, exist_ok=True)

    custom_dir = tmp_path / "broken_skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "skill.json").write_text(
        '{"name":"broken_skill","version":"1.0.0","description":"x","required_tools":["__not_exist_tool__"]}',
        encoding="utf-8",
    )

    result = mgr.check()
    assert result["ok"] is False
    assert any(c["name"] == "broken_skill" and "__not_exist_tool__" in c["missing_tools"] for c in result["checks"])


def test_search_returns_catalog_match(tmp_path: Path, monkeypatch):
    _mock_config(monkeypatch)
    mgr = SkillManager()
    mgr.skills_dir = tmp_path
    mgr.skills_dir.mkdir(parents=True, exist_ok=True)

    results = mgr.search("araştır")
    assert any(r["name"] == "research" for r in results)


@pytest.mark.asyncio
async def test_execute_routes_tool_through_task_executor(monkeypatch):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "get_skill", lambda _name: {"enabled": True})
    seen = {}

    async def write_file(path: str = "", content: str = ""):
        return {"success": True, "path": path, "content": content}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "ok"}

    original = tools._loaded_tools.get("write_file")
    tools._loaded_tools["write_file"] = write_file
    monkeypatch.setattr("core.skills.manager.TaskExecutor.execute", fake_execute)

    try:
        result = await mgr.execute("files", "write_file", {"path": "/tmp/x.txt", "content": "hi"})
    finally:
        if original is None:
            tools._loaded_tools.pop("write_file", None)
        else:
            tools._loaded_tools["write_file"] = original

    assert seen["tool_name"] == "write_file"
    assert seen["params"] == {"path": "/tmp/x.txt", "content": "hi"}
    assert result["success"] is True
    assert result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_preserves_outer_shape_for_malformed_normalized_result(monkeypatch):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "get_skill", lambda _name: {"enabled": True})

    async def read_file(path: str = ""):
        return None

    original = tools._loaded_tools.get("read_file")
    tools._loaded_tools["read_file"] = read_file

    try:
        result = await mgr.execute("files", "read_file", {"path": "/tmp/missing.txt"})
    finally:
        if original is None:
            tools._loaded_tools.pop("read_file", None)
        else:
            tools._loaded_tools["read_file"] = original

    assert result["success"] is True
    assert result["result"]["status"] == "failed"
    assert result["result"]["error_code"] == "TOOL_CONTRACT_VIOLATION"


@pytest.mark.asyncio
async def test_execute_returns_tool_not_found_when_registry_entry_missing(monkeypatch):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "get_skill", lambda _name: {"enabled": True})
    monkeypatch.setattr(type(tools.AVAILABLE_TOOLS), "__contains__", lambda self, key: True)
    monkeypatch.setattr(type(tools.AVAILABLE_TOOLS), "get", lambda self, key, default=None: None)

    result = await mgr.execute("files", "ghost_tool", {})

    assert result["success"] is False
    assert result["error"] == "Tool not found: ghost_tool"
