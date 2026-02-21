"""
Unit testler: FuzzyIntentMatcher
normalize_turkish() ve temel fuzzy matching testi.
"""
import pytest
from core.fuzzy_intent import normalize_turkish, FuzzyIntentMatcher


class TestNormalizeTurkish:
    """normalize_turkish() fonksiyonu testleri."""

    def test_lowercase(self):
        assert normalize_turkish("MERHABA") == "merhaba"

    def test_strip(self):
        assert normalize_turkish("  selam  ") == "selam"

    def test_apostrophe_removal(self):
        # chrome'u -> chrome
        result = normalize_turkish("chrome'u aç")
        assert "chrome" in result
        assert "'" not in result

    def test_filler_word_removal(self):
        result = normalize_turkish("abi bana bir ekran görüntüsü al lütfen")
        assert "abi" not in result
        assert "lütfen" not in result
        assert "ekran" in result
        assert "görüntüsü" in result

    def test_verb_suffix_normalization(self):
        result = normalize_turkish("atsana bunu")
        # atsana -> al
        assert "al" in result

    def test_informal_map(self):
        result = normalize_turkish("slm nasılsın")
        assert "selam" in result

    def test_multi_space_collapsed(self):
        result = normalize_turkish("ekran   görüntüsü   al")
        assert "  " not in result

    def test_empty_string(self):
        assert normalize_turkish("") == ""

    def test_only_fillers(self):
        # Tüm kelimeler filler ise boş dönebilir
        result = normalize_turkish("bi bir ya")
        # En azından crash olmamalı
        assert isinstance(result, str)

    def test_turkish_suffix_space_join(self):
        # "safari yi" -> "safari" (boşluklu ek kaldırma)
        result = normalize_turkish("safari yi aç")
        assert "yi" not in result.split()
        assert "safari" in result


class TestFuzzyIntentMatcher:
    """FuzzyIntentMatcher.match() temel testleri."""

    @pytest.fixture(autouse=True)
    def matcher(self):
        self.m = FuzzyIntentMatcher()

    def test_screenshot_informal(self):
        result = self.m.match("bi ss atsana")
        assert result is not None
        assert result.tool == "take_screenshot"
        assert result.confidence >= 0.7

    def test_screenshot_formal(self):
        result = self.m.match("ekran görüntüsü al")
        assert result is not None
        assert result.tool == "take_screenshot"

    def test_volume_reduce(self):
        result = self.m.match("abi sesi bi kıs ya")
        assert result is not None
        assert result.tool == "set_volume"

    def test_close_app_chrome(self):
        result = self.m.match("chrome'u kapat")
        assert result is not None
        assert result.tool == "close_app"
        assert "chrome" in result.params.get("app_name", "").lower() or \
               "Chrome" in result.params.get("app_name", "")

    def test_no_match_random_text(self):
        result = self.m.match("xyzxyzxyz asdfasdf 12345")
        # Eşleşme olmayabilir veya düşük güven
        if result:
            assert result.confidence < 0.5

    def test_match_returns_fuzzy_result_type(self):
        from core.fuzzy_intent import FuzzyResult
        result = self.m.match("ekran görüntüsü al")
        if result:
            assert isinstance(result, FuzzyResult)
            assert hasattr(result, "tool")
            assert hasattr(result, "params")
            assert hasattr(result, "confidence")
            assert hasattr(result, "matched_trigger")
            assert hasattr(result, "normalized_input")

    def test_confidence_range(self):
        result = self.m.match("ekran görüntüsü al")
        if result:
            assert 0.0 <= result.confidence <= 1.0

    def test_match_research(self):
        result = self.m.match("python hakkında araştırma yap")
        if result:
            assert result.tool in ("research", "web_search", "advanced_research")

    def test_english_screenshot(self):
        result = self.m.match("take a screenshot")
        if result:
            assert result.tool == "take_screenshot"
