from config.settings_manager import DEFAULT_SETTINGS


def test_new_stabilization_defaults_exist():
    assert DEFAULT_SETTINGS["llm_fallback_mode"] in {"aggressive", "conservative"}
    assert isinstance(DEFAULT_SETTINGS["llm_fallback_order"], list)
    assert "ollama" in DEFAULT_SETTINGS["llm_fallback_order"]
    assert DEFAULT_SETTINGS["assistant_style"] == "natural_concise"
    assert DEFAULT_SETTINGS["communication_tone"] == "natural_concise"
    assert DEFAULT_SETTINGS["conversation_privacy_mode"] == "balanced"
    assert DEFAULT_SETTINGS["liteparse_enabled"] is True
    assert DEFAULT_SETTINGS["repair_aggressiveness"] == "balanced"
    assert DEFAULT_SETTINGS["mobile_channel_enablement"]["telegram"] is True
    assert DEFAULT_SETTINGS["mobile_channel_enablement"]["sms"] is False
    assert DEFAULT_SETTINGS["photo_save_dir"].startswith("~/")
    assert DEFAULT_SETTINGS["document_save_dir"].startswith("~/")
