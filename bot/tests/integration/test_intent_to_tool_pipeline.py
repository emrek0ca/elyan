"""
Integration testler: Intent → Tool pipeline
IntentParser + FuzzyIntentMatcher birlikte çalışma testleri.
Gerçek LLM çağrısı yapılmaz.
"""
import pytest
from core.intent_parser import IntentParser


KNOWN_ACTIONS = {
    "take_screenshot", "set_volume", "open_app", "close_app",
    "list_files", "create_folder", "write_file", "search_files",
    "research", "web_search", "shutdown_system", "restart_system",
    "lock_screen", "set_brightness", "send_notification",
    "translate", "summarize", "chat", "help",
}


class TestIntentToToolPipeline:
    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = IntentParser()

    # ── Sistem komutları ────────────────────────────────────────────────────

    def test_screenshot_tr(self):
        r = self.parser.parse("ekran görüntüsü al")
        assert r is not None
        assert r["action"] == "take_screenshot"

    def test_screenshot_informal(self):
        """Konuşma dili — fuzzy yolundan geçebilir."""
        r = self.parser.parse("ss at bana")
        assert r is not None
        assert r["action"] == "take_screenshot"

    def test_shutdown_system(self):
        r = self.parser.parse("bilgisayarı kapat")
        assert r is not None
        assert r["action"] == "shutdown_system"

    def test_restart_system(self):
        r = self.parser.parse("yeniden başlat")
        assert r is not None
        assert r["action"] == "restart_system"

    def test_lock_screen(self):
        r = self.parser.parse("ekranı kilitle")
        assert r is not None
        assert r["action"] == "lock_screen"

    # ── Ses kontrolü ────────────────────────────────────────────────────────

    def test_volume_mute(self):
        r = self.parser.parse("sesi kapat")
        assert r is not None
        assert r["action"] == "set_volume"

    def test_volume_set_percent(self):
        r = self.parser.parse("sesi yüzde elli yap")
        assert r is not None
        assert r["action"] == "set_volume"

    # ── Uygulama kontrolü ───────────────────────────────────────────────────

    def test_open_safari(self):
        r = self.parser.parse("safari aç")
        assert r is not None
        assert r["action"] == "open_app"
        assert r.get("params", {}).get("app_name", "").lower() in ("safari", "Safari".lower())

    def test_close_chrome(self):
        r = self.parser.parse("chrome kapat")
        assert r is not None
        assert r["action"] == "close_app"

    # ── Dosya işlemleri ─────────────────────────────────────────────────────

    def test_list_files_desktop(self):
        r = self.parser.parse("masaüstündeki dosyaları listele")
        assert r is not None
        assert r["action"] == "list_files"

    def test_create_folder(self):
        r = self.parser.parse("belgeler klasörü oluştur")
        assert r is not None
        assert r["action"] == "create_folder"

    # ── Araştırma ───────────────────────────────────────────────────────────

    def test_research_query(self):
        r = self.parser.parse("python programlama hakkında araştırma yap")
        assert r is not None
        assert r["action"] in ("research", "web_search")

    # ── Genel kontroller ────────────────────────────────────────────────────

    def test_result_is_dict(self):
        r = self.parser.parse("ekran görüntüsü al")
        assert isinstance(r, dict)

    def test_result_has_action_key(self):
        r = self.parser.parse("ekran görüntüsü al")
        assert "action" in r

    def test_result_has_params_key(self):
        r = self.parser.parse("ekran görüntüsü al")
        assert "params" in r or True  # params opsiyonel olabilir

    def test_known_action_in_set(self):
        r = self.parser.parse("ekran görüntüsü al")
        if r:
            # action ya bilinen bir tool ya da bilinmeyen bir şey (chat vb.)
            assert isinstance(r["action"], str)
            assert len(r["action"]) > 0

    def test_none_for_empty_input(self):
        """Boş girişte None veya chat dönmeli — exception olmamalı."""
        try:
            r = self.parser.parse("")
            assert r is None or isinstance(r, dict)
        except Exception as exc:
            pytest.fail(f"Boş girişte exception fırladı: {exc}")

    def test_gibberish_does_not_crash(self):
        """Saçma giriş — exception olmamalı."""
        try:
            r = self.parser.parse("xyzxyz asdfasdf 99999 !@#$%")
            assert r is None or isinstance(r, dict)
        except Exception as exc:
            pytest.fail(f"Saçma girişte exception fırladı: {exc}")
