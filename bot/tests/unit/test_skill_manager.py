from pathlib import Path

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
