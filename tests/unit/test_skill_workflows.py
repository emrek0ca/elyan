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

    text = (
        "https://httpbin.org/get için health check yap, sonra GET at, "
        "sonucu ~/Desktop/elyan-test/api/result.json ve summary.md kaydet."
    )
    intent = mgr.resolve_workflow_intent(text, attachments=[], file_context={})
    assert intent is not None
    assert intent["action"] == "api_health_get_save"
    assert intent["_workflow_id"] == "api_health_get_save"
    assert intent["params"]["url"] == "https://httpbin.org/get"
    assert Path(intent["params"]["result_path"]).as_posix().endswith("/Desktop/elyan-test/api/result.json")
    assert Path(intent["params"]["summary_path"]).name == "summary.md"
