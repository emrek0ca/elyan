from config.settings_manager import DEFAULT_SETTINGS


def test_new_stabilization_defaults_exist():
    assert DEFAULT_SETTINGS["llm_fallback_mode"] in {"aggressive", "conservative"}
    assert isinstance(DEFAULT_SETTINGS["llm_fallback_order"], list)
    assert "ollama" in DEFAULT_SETTINGS["llm_fallback_order"]
    assert DEFAULT_SETTINGS["assistant_style"] == "professional_friendly_short"
    assert DEFAULT_SETTINGS["photo_save_dir"].startswith("~/")
    assert DEFAULT_SETTINGS["document_save_dir"].startswith("~/")
