from pathlib import Path

from core.skills.manager import SkillManager


def test_list_workflows_runtime_ready_and_enabled(monkeypatch):
    mgr = SkillManager()

    monkeypatch.setattr(
        mgr,
        "_available_tools_set",
        lambda: {"set_wallpaper", "take_screenshot", "api_health_check", "http_request", "write_file"},
    )
    monkeypatch.setattr(
        mgr,
        "list_skills",
        lambda **kwargs: [{"name": "system", "enabled": True}, {"name": "files", "enabled": True}],
    )
    monkeypatch.setattr(mgr, "_enabled_workflow_set", lambda: {"wallpaper_with_proof"})
    monkeypatch.setattr(mgr, "_disabled_workflow_set", lambda: set())
    monkeypatch.setattr(mgr, "_mission_recipe_workflows", lambda: [])

    items = mgr.list_workflows(enabled_only=True)
    assert len(items) == 1
    wf = items[0]
    assert wf["id"] == "wallpaper_with_proof"
    assert wf["enabled"] is True
    assert wf["runtime_ready"] is True
    assert wf["missing_tools"] == []
    assert wf["missing_skills"] == []


def test_resolve_workflow_intent_wallpaper_with_attachment(monkeypatch, tmp_path):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "_enabled_workflow_set", lambda: {"wallpaper_with_proof"})
    monkeypatch.setattr(mgr, "_disabled_workflow_set", lambda: set())
    monkeypatch.setattr(mgr, "_mission_recipe_workflows", lambda: [])

    img = tmp_path / "dog.jpg"
    img.write_bytes(b"jpg")

    intent = mgr.resolve_workflow_intent(
        "Bunu duvar kağıdı yap",
        attachments=[str(img)],
        file_context={},
    )
    assert intent is not None
    assert intent["action"] == "set_wallpaper"
    assert intent["params"]["image_path"] == str(img)
    assert intent["_workflow_id"] == "wallpaper_with_proof"


def test_resolve_workflow_intent_api_health_get_save(monkeypatch):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "_enabled_workflow_set", lambda: {"api_health_get_save"})
    monkeypatch.setattr(mgr, "_disabled_workflow_set", lambda: set())
    monkeypatch.setattr(mgr, "_mission_recipe_workflows", lambda: [])

    text = (
        "https://httpbin.org/get için health check yap, sonra GET at, "
        "sonucu ~/Desktop/elyan-test/api/result.json ve summary.txt kaydet."
    )
    intent = mgr.resolve_workflow_intent(text, attachments=[], file_context={})
    assert intent is not None
    assert intent["action"] == "api_health_get_save"
    assert intent["_workflow_id"] == "api_health_get_save"
    assert intent["params"]["url"] == "https://httpbin.org/get"
    assert Path(intent["params"]["result_path"]).as_posix().endswith("/Desktop/elyan-test/api/result.json")
    assert Path(intent["params"]["summary_path"]).name == "summary.txt"


def test_list_workflows_includes_mission_recipe(monkeypatch):
    mgr = SkillManager()
    monkeypatch.setattr(mgr, "_available_tools_set", lambda: set())
    monkeypatch.setattr(mgr, "list_skills", lambda **kwargs: [])
    monkeypatch.setattr(mgr, "_enabled_workflow_set", lambda: set())
    monkeypatch.setattr(mgr, "_disabled_workflow_set", lambda: set())
    monkeypatch.setattr(
        mgr,
        "_mission_recipe_workflows",
        lambda: [
            {
                "id": "skill_landing_page_recipe",
                "name": "Landing Page SOP",
                "description": "Mission recipe workflow (code).",
                "category": "code",
                "required_skills": [],
                "required_tools": [],
                "steps": ["Plan", "Build", "Verify", "Deliver"],
                "trigger_markers": [],
                "executable": True,
                "auto_intent": False,
                "runtime_ready": True,
                "source": "mission_recipe",
                "source_mission_id": "mission_123",
                "verification_rules": ["lint", "test"],
                "tool_policy": {"local_only": True},
                "output_contract": {"route_mode": "code"},
            }
        ],
    )

    items = mgr.list_workflows()
    recipe = next(item for item in items if item["id"] == "skill_landing_page_recipe")
    assert recipe["source"] == "mission_recipe"
    assert recipe["enabled"] is True
    assert recipe["runtime_ready"] is True
    assert recipe["source_mission_id"] == "mission_123"
    assert recipe["steps"] == ["Plan", "Build", "Verify", "Deliver"]


def test_set_workflow_enabled_supports_mission_recipe(monkeypatch):
    mgr = SkillManager()
    state = {"disabled": set()}
    monkeypatch.setattr(mgr, "_available_tools_set", lambda: set())
    monkeypatch.setattr(mgr, "list_skills", lambda **kwargs: [])
    monkeypatch.setattr(mgr, "_enabled_workflow_set", lambda: set())
    monkeypatch.setattr(mgr, "_set_enabled_workflow_set", lambda enabled: None)
    monkeypatch.setattr(mgr, "_disabled_workflow_set", lambda: set(state["disabled"]))
    monkeypatch.setattr(mgr, "_set_disabled_workflow_set", lambda disabled: state.__setitem__("disabled", set(disabled)))
    monkeypatch.setattr(
        mgr,
        "_mission_recipe_workflows",
        lambda: [
            {
                "id": "skill_recipe_one",
                "name": "Recipe One",
                "description": "Mission recipe workflow.",
                "category": "mission",
                "required_skills": [],
                "required_tools": [],
                "steps": ["Plan"],
                "trigger_markers": [],
                "executable": True,
                "auto_intent": False,
                "runtime_ready": True,
                "source": "mission_recipe",
            }
        ],
    )

    ok, message, info = mgr.set_workflow_enabled("skill_recipe_one", False)
    assert ok is True
    assert "devre dışı bırakıldı" in message
    assert "skill_recipe_one" in state["disabled"]
    assert info is not None
    assert info["enabled"] is False
