from __future__ import annotations

from core.skills.registry import skill_registry


def test_skill_registry_exposes_builtin_skills_and_command_map():
    skill_registry.refresh()

    enabled = {item["name"] for item in skill_registry.list_skills(available=True, enabled_only=True)}
    workflows = {item["id"] for item in skill_registry.list_workflows(enabled_only=True)}

    assert {"browser", "files", "office", "research", "system"} <= enabled
    assert {"wallpaper_with_proof", "api_health_get_save"} <= workflows
    assert skill_registry.get_skill_for_command("navigate")["name"] == "browser"
    assert skill_registry.get_skill_for_command("write")["name"] == "files"


def test_skill_registry_resolves_operator_and_file_intents():
    browser = skill_registry.resolve_from_intent("openai.com aç", {"metadata": {}})
    browser_app = skill_registry.resolve_from_intent("Safari’de openai.com aç", {"metadata": {}})
    file_task = skill_registry.resolve_from_intent("Masaüstüne not.txt yaz", {"metadata": {}})

    assert browser["skill"]["name"] == "browser"
    assert browser_app["skill"]["name"] == "browser"
    assert file_task["skill"]["name"] == "files"
    assert file_task["route"]["domain"] == "file_ops"
