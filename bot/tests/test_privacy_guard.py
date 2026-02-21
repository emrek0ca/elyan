from security.privacy_guard import redact_text, sanitize_object
from core.task_engine import TaskEngine


def test_redact_text_masks_common_sensitive_tokens():
    text = "mailim test@example.com token sk-abcd12345678901234"
    out = redact_text(text)
    assert "test@example.com" not in out
    assert "sk-abcd12345678901234" not in out
    assert "[REDACTED_EMAIL]" in out


def test_sanitize_object_recursive():
    payload = {"email": "john@doe.com", "nested": {"token": "sk-abc1234567890"}}
    out = sanitize_object(payload)
    assert out["email"] != "john@doe.com"
    assert "REDACTED" in out["email"]
    assert "REDACTED" in out["nested"]["token"]


def test_extract_execution_requirements():
    engine = TaskEngine()
    req = engine._extract_execution_requirements("Bunu çok detaylı ve profesyonel yap, PDF olarak acil hazırla")
    assert req.get("quality_level") == "high"
    assert req.get("preferred_output") == "pdf"
    assert req.get("urgency") == "high"
