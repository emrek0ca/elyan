from core.fast_response import FastResponseSystem


def test_fast_response_handles_naber_naturally():
    system = FastResponseSystem()
    result = system.get_fast_response("naber")
    assert result is not None
    assert "nasılsın" in result.answer.lower()


def test_fast_response_handles_colloquial_what_are_you_doing():
    system = FastResponseSystem()
    result = system.get_fast_response("napıosun")
    assert result is not None
    assert result.answer
    assert "Merhaba. Nasıl yardımcı olayım?" not in result.answer


def test_fast_response_handles_identity_shortcuts():
    system = FastResponseSystem()
    result = system.get_fast_response("adın")
    assert result is not None
    assert "Elyan" in result.answer or "Elyan" in result.answer.replace("'", "")


def test_fast_response_handles_contextual_followups():
    system = FastResponseSystem()
    result = system.get_fast_response("hangi alanlarda mesela", context={"last_topic": "yapay zeka"})
    assert result is not None
    assert "sağlık" in result.answer.lower()
