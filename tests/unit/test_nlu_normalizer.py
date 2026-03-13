from core.nlu_normalizer import normalize_turkish_ascii, normalize_turkish_text
from core.quick_intent import QuickIntentDetector, IntentCategory
from core.fast_response import FastResponseSystem


def test_normalize_turkish_text_handles_slang_and_typos():
    assert normalize_turkish_text("napıosun") == "ne yapıyorsun"
    assert normalize_turkish_text("mrb") == "merhaba"
    assert normalize_turkish_text("chromea geç") == "chrome a geç"
    assert normalize_turkish_text("safariyi aç") == "safari yi aç"
    assert normalize_turkish_text("terminalde pwd çalıştır") == "terminal de pwd çalıştır"
    assert normalize_turkish_text("googlea girip ara") == "google a girip ara"


def test_normalize_turkish_ascii_handles_suffix_forms():
    assert normalize_turkish_ascii("safari'ye geç") == "safari ye gec"
    assert normalize_turkish_ascii("masaüstündeki dosya") == "masaustundeki dosya"


def test_quick_intent_uses_normalized_input_for_chat_variants():
    detector = QuickIntentDetector()
    result = detector.detect("napıosun")
    assert result.category == IntentCategory.CHAT


def test_fast_response_uses_normalized_input_for_chat_variants():
    system = FastResponseSystem()
    result = system.get_fast_response("mrb")
    assert result is not None
    assert "yardımcı" in result.answer.lower() or "ne yapalım" in result.answer.lower() or "dinliyorum" in result.answer.lower() or "buradayım" in result.answer.lower()
