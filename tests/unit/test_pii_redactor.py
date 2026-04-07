from core.privacy.redactor import PIIRedactor


def test_redact_text_patterns():
    redactor = PIIRedactor()
    result = redactor.redact("mail a@b.com token eyJabc.def.ghi phone +90 555 123 45 67")
    assert result.redacted is True
    assert "[REDACTED]" in result.value
    assert "EMAIL" in result.matches
    assert "JWT_TOKEN" in result.matches


def test_redact_dict_masks_sensitive_keys():
    redactor = PIIRedactor()
    result = redactor.redact_dict({"token": "secret", "nested": {"email": "test@example.com"}})
    assert result.redacted is True
    assert result.value["token"] == "[REDACTED]"
    assert result.value["nested"]["email"] == "[REDACTED]"
