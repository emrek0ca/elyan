from core.conversation_context import ConversationContextManager


def test_conversation_context_extracts_last_topic_file_and_app():
    manager = ConversationContextManager()
    history = [
        {"role": "user", "content": "Yapay zeka nedir"},
        {"role": "assistant", "content": "Yapay zeka hakkında örnekler verebilirim."},
        {"role": "user", "content": "Chrome'da openai.com aç"},
        {"role": "assistant", "content": "Tamam, openai.com açıyorum."},
        {"role": "user", "content": "Bu dosyayı /tmp/rapor.pdf olarak kaydet"},
    ]

    context = manager.extract_context(history)

    assert context["last_topic"] == "Bu dosyayı /tmp/rapor.pdf olarak kaydet"
    assert context["last_app"] == "chrome"
    assert context["last_file"] == "/tmp/rapor.pdf"
    assert context["recent_topics"]


def test_conversation_context_resolves_followups_and_references():
    manager = ConversationContextManager()
    context = {
        "last_topic": "yapay zeka",
        "last_task": "Google Calendar'a toplantı ekle",
        "last_url": "https://openai.com",
        "last_file": "/tmp/rapor.pdf",
        "last_app": "chrome",
    }

    assert manager.resolve_references("hangi alanlarda mesela", context).startswith("yapay zeka")
    assert manager.resolve_references("onu aç", context) == "https://openai.com aç"
    assert manager.resolve_references("bunu aç", context) == "/tmp/rapor.pdf aç"

