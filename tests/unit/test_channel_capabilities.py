from core.gateway.channel_capabilities import resolve_channel_capabilities


def test_resolve_channel_capabilities_uses_matrix_defaults():
    caps = resolve_channel_capabilities("telegram", {})
    assert caps["buttons"] is True
    assert caps["images"] is True
    assert caps["text_limit"] >= 300


def test_resolve_channel_capabilities_merges_adapter_overrides():
    caps = resolve_channel_capabilities(
        "discord",
        {"markdown": False, "buttons": False, "text_limit": 4200},
    )
    assert caps["markdown"] is False
    assert caps["buttons"] is False
    assert caps["text_limit"] == 4200


def test_resolve_channel_capabilities_unknown_channel_falls_back_default():
    caps = resolve_channel_capabilities("unknown-x", {})
    assert caps["buttons"] is False
    assert caps["files"] is False
    assert caps["text_limit"] == 3500

