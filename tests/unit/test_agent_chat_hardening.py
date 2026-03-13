from core.agent import Agent


def test_agent_fast_chat_reply_shortcuts_greeting():
    out = Agent._fast_chat_reply("selam")
    assert out
    assert "Deliverable Spec" not in out
    assert len(str(out).splitlines()) <= 2


def test_agent_sanitize_chat_reply_strips_internal_markers():
    raw = (
        "Merhaba!\n"
        "Deliverable Spec: Kullanıcıya yardımcı olmak\n"
        "Done Criteria: Kullanıcı memnun olsun\n\n"
        "Nasıl yardımcı olayım?"
    )
    out = Agent._sanitize_chat_reply(raw)
    assert "Deliverable Spec" not in out
    assert "Done Criteria" not in out
    assert out == "Merhaba!\n\nNasıl yardımcı olayım?"


def test_agent_sanitize_chat_reply_strips_system_note_and_gate_lines():
    raw = (
        "Fatih Terim eski futbolcu ve teknik direktördür.\n"
        "Sistem notu: Yüksek Bellek kullanımı şu an %86.\n"
        "- Kullanıcının ihtiyacını belirlemek\n"
        "❌ Completion gate failed: completion:no_successful_tool_result"
    )
    out = Agent._sanitize_chat_reply(raw)
    assert "Sistem notu" not in out
    assert "Completion gate failed" not in out
    assert "- Kullanıcının" not in out
    assert out == "Fatih Terim eski futbolcu ve teknik direktördür."


def test_agent_information_question_prompt_is_direct():
    out = Agent._build_information_question_prompt("Fatih Terim kimdir")
    assert "Önceki konuşmayı referans alma." in out
    assert "2-4 cümlede ver" in out
    assert "Fatih Terim kimdir" in out


def test_agent_information_question_classifier_distinguishes_chat_and_commands():
    assert Agent._is_information_question("Fatih Terim kimdir")
    assert not Agent._is_information_question("naber")
    assert not Agent._is_information_question("napıosun")
    assert not Agent._is_information_question("chromea geç")
    assert not Agent._is_information_question("safariyi aç")
