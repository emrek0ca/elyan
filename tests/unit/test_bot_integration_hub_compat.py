"""Regression coverage for the legacy bot integration hub copy."""

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def test_bot_integration_hub_no_placeholder_notes():
    source = (_REPO / "core/integration_hub.py").read_text(encoding="utf-8")

    assert "This is a placeholder" not in source
    assert "not yet fully implemented" not in source
    assert "Email sending not yet fully implemented" not in source
    assert "Calendar integration not yet fully implemented" not in source
    assert "Cloud storage upload not yet fully implemented" not in source
    assert "from tools.email_tools import EmailManager" in source
    assert "from integrations.connectors.google import GoogleConnector" in source
