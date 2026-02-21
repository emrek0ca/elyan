"""Unit tests for gateway API secret masking helpers."""

from core.gateway.server import _mask_sensitive_fields


def test_mask_sensitive_fields_masks_tokens_and_keys():
    payload = {
        "type": "telegram",
        "token": "123:secret",
        "nested": {
            "apiKey": "abc",
            "password": "pw",
            "normal": "ok",
        },
    }
    masked = _mask_sensitive_fields(payload)
    assert masked["token"] == "***"
    assert masked["nested"]["apiKey"] == "***"
    assert masked["nested"]["password"] == "***"
    assert masked["nested"]["normal"] == "ok"


def test_mask_sensitive_fields_masks_lists():
    payload = [{"bot_token": "x"}, {"value": "y"}]
    masked = _mask_sensitive_fields(payload)
    assert masked[0]["bot_token"] == "***"
    assert masked[1]["value"] == "y"
