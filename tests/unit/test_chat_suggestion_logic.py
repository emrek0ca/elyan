from ui.clean_chat_widget import CleanChatWidget


def test_chat_widget_suggestion_logic_without_qt_init():
    widget = CleanChatWidget.__new__(CleanChatWidget)
    class _Btn:
        def __init__(self):
            self.text = ""
        def setText(self, value):
            self.text = value
    widget._suggestion_buttons = [_Btn(), _Btn(), _Btn(), _Btn()]
    widget._suggestions = []
    CleanChatWidget._refresh_suggestions_from_response(widget, "telefon bağlantısı ve mobile dispatch hazır")
    assert widget._suggestion_buttons[0].text == "Telefon bağlantısını tekrar kontrol et"


def test_chat_widget_operator_tone_helpers():
    assert CleanChatWidget._operator_tone({"status": "healthy", "verification_state": "strong"}) == "verified"
    assert CleanChatWidget._operator_tone({"status": "healthy", "fallback_active": True}) == "degraded"
    assert CleanChatWidget._operator_caption("Speed", {"current_lane": "turbo_lane"}) == "Speed turbo"
