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
