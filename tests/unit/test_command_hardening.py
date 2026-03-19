import pytest

from core.command_hardening import (
    chat_output_needs_retry,
    classify_command_route,
    sanitize_chat_output,
    screen_state_is_actionable,
)


def test_sanitize_chat_output_strips_json_tables_and_meta():
    raw = (
        "```json\n"
        "{\"message\":\"Merhaba\",\"meta\":\"x\"}\n"
        "```\n"
        "| a | b |\n"
        "| --- | --- |\n"
        "Tabii ki, yardımcı olayım.\n"
        "Merhaba!\n"
        "Merhaba!\n"
        "Nasıl yardımcı olayım?"
    )

    out = sanitize_chat_output(raw)

    assert "```" not in out
    assert "|" not in out
    assert "Tabii ki" not in out
    assert out.startswith("Merhaba!")
    assert "Nasıl yardımcı olayım?" in out


def test_chat_output_needs_retry_for_fenced_json():
    raw = "```json\n{\"message\":\"Merhaba\"}\n```"

    assert chat_output_needs_retry(raw) is True


@pytest.mark.parametrize(
    "text",
    [
        "SMS kodunu geç",
        "Giriş yap",
        "login ol",
        "sudo çalıştır",
        "hepsini sil",
        "mikrofonu aç",
        "görünmeyen UI'da tıkla",
    ],
)
def test_classify_command_route_refuses_unsupported_actions(text):
    decision = classify_command_route(text)

    assert decision.refusal is True
    assert decision.mode == "communication"
    assert decision.should_bypass_pipeline is True
    assert decision.refusal_message


def test_screen_state_is_actionable_accepts_fused_payload():
    ok, reason = screen_state_is_actionable(
        {
            "confidence": 0.78,
            "accessibility": [{"label": "Search field", "role": "text_field"}],
            "ocr_text": "Search kittens",
            "cursor": {"x": 1, "y": 2},
        }
    )

    assert ok is True
    assert reason == ""
