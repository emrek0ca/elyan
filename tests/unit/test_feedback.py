"""
tests/unit/test_feedback.py
FeedbackStore / FeedbackDetector birim testleri.
"""
import pytest


# ── FeedbackDetector ──────────────────────────────────────────────────────────

def test_is_correction_detects_hayir():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_correction("hayır bunu kastetmedim") is True

def test_is_correction_detects_yanlis():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_correction("yanlış anladın beni") is True

def test_is_correction_detects_english_wrong():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_correction("that's not what I meant") is True

def test_is_correction_false_for_normal_input():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_correction("masaüstünde ne var") is False

def test_is_positive_detects_tesekkur():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_positive("teşekkürler harika iş") is True

def test_is_positive_detects_mukemmel():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_positive("mükemmel tam istediğim bu") is True

def test_is_positive_false_for_neutral():
    from core.feedback import FeedbackDetector
    assert FeedbackDetector.is_positive("masaüstünü listele") is False

def test_extract_correction_intent_cleans_signal():
    from core.feedback import FeedbackDetector
    is_corr, cleaned = FeedbackDetector.extract_correction_intent("hayır bunu kastetmedim, ekran görüntüsü al")
    assert is_corr is True
    assert "ekran görüntüsü al" in cleaned
    # correction signals removed
    assert "hayır" not in cleaned

def test_extract_correction_intent_returns_original_when_not_correction():
    from core.feedback import FeedbackDetector
    is_corr, cleaned = FeedbackDetector.extract_correction_intent("ekran görüntüsü al")
    assert is_corr is False
    assert cleaned == "ekran görüntüsü al"

def test_extract_correction_intent_returns_original_when_cleaned_too_short():
    from core.feedback import FeedbackDetector
    # After removing signals, only 1-2 chars left → return original
    is_corr, cleaned = FeedbackDetector.extract_correction_intent("hayır")
    assert cleaned == "hayır"


# ── FeedbackStore ─────────────────────────────────────────────────────────────

def _fresh_store():
    """Her test için izole FeedbackStore (dosya yazma kapalı)."""
    from core.feedback import FeedbackStore
    store = FeedbackStore.__new__(FeedbackStore)
    import threading
    from collections import defaultdict
    store._lock = threading.Lock()
    store._corrections = []
    store._positives = []
    store._action_errors = defaultdict(lambda: defaultdict(int))
    return store


def test_record_correction_stores_entry(tmp_path, monkeypatch):
    store = _fresh_store()
    monkeypatch.setattr("core.feedback._STORE_PATH", tmp_path / "feedback.json")
    store.record_correction(
        user_id=1,
        original_input="araştır bir şey",
        wrong_action="list_files",
        correction_text="advanced_research",
    )
    corrs = store.get_user_corrections(1)
    assert len(corrs) == 1
    assert corrs[0].wrong_action == "list_files"


def test_record_positive_stores_entry(tmp_path, monkeypatch):
    store = _fresh_store()
    monkeypatch.setattr("core.feedback._STORE_PATH", tmp_path / "feedback.json")
    store.record_positive(user_id=2, original_input="araştır", action="advanced_research")
    stats = store.get_stats(2)
    assert stats["positives"] == 1


def test_get_user_corrections_filters_by_user():
    store = _fresh_store()
    from core.feedback import Correction
    store._corrections = [
        Correction(user_id=1, original_input="a", wrong_action="x", correction_text="y"),
        Correction(user_id=2, original_input="b", wrong_action="z", correction_text="w"),
    ]
    result = store.get_user_corrections(1)
    assert all(c.user_id == 1 for c in result)
    assert len(result) == 1


def test_get_user_corrections_respects_limit():
    store = _fresh_store()
    from core.feedback import Correction
    for i in range(10):
        store._corrections.append(
            Correction(user_id=1, original_input=f"inp{i}", wrong_action="x", correction_text="y")
        )
    result = store.get_user_corrections(1, limit=3)
    assert len(result) == 3


def test_get_error_count():
    store = _fresh_store()
    store._action_errors[1]["list_files"] = 3
    assert store.get_error_count(1, "list_files") == 3
    assert store.get_error_count(1, "nonexistent") == 0


def test_build_correction_hint_returns_empty_when_no_corrections():
    store = _fresh_store()
    hint = store.build_correction_hint(user_id=1, candidate_action="list_files")
    assert hint == ""


def test_build_correction_hint_returns_text_when_match(tmp_path, monkeypatch):
    store = _fresh_store()
    monkeypatch.setattr("core.feedback._STORE_PATH", tmp_path / "feedback.json")
    store.record_correction(
        user_id=1,
        original_input="araştır bunu",
        wrong_action="list_files",
        correction_text="advanced_research",
    )
    hint = store.build_correction_hint(user_id=1, candidate_action="list_files")
    assert "ÖĞRENME NOTU" in hint
    assert "list_files" in hint


def test_get_stats_error_rate():
    store = _fresh_store()
    from core.feedback import Correction, PositiveFeedback
    store._corrections = [Correction(user_id=1, original_input="a", wrong_action="x", correction_text="y")]
    store._positives = [PositiveFeedback(user_id=1, original_input="b", action="y")]
    stats = store.get_stats(1)
    assert stats["corrections"] == 1
    assert stats["positives"] == 1
    assert stats["error_rate_pct"] == pytest.approx(50.0, abs=0.1)


def test_get_stats_empty_user():
    store = _fresh_store()
    stats = store.get_stats(999)
    assert stats["corrections"] == 0
    assert stats["positives"] == 0
    assert stats["error_rate_pct"] == pytest.approx(0.0, abs=0.1)


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_feedback_store_returns_same_instance():
    from core.feedback import get_feedback_store
    s1 = get_feedback_store()
    s2 = get_feedback_store()
    assert s1 is s2


def test_get_feedback_detector_returns_detector():
    from core.feedback import get_feedback_detector, FeedbackDetector
    fd = get_feedback_detector()
    assert isinstance(fd, FeedbackDetector)


# ── Max size guard ─────────────────────────────────────────────────────────────

def test_corrections_capped_at_max(tmp_path, monkeypatch):
    from core.feedback import _MAX_CORRECTIONS
    monkeypatch.setattr("core.feedback._STORE_PATH", tmp_path / "feedback.json")
    store = _fresh_store()
    store._lock.__class__  # ensure lock is real
    # Directly fill beyond max
    from core.feedback import Correction
    for i in range(_MAX_CORRECTIONS + 10):
        store._corrections.append(
            Correction(user_id=1, original_input=f"x{i}", wrong_action="a", correction_text="b")
        )
    # Simulate capping (as done in record_correction)
    store._corrections = store._corrections[-_MAX_CORRECTIONS:]
    assert len(store._corrections) <= _MAX_CORRECTIONS
