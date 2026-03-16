import pytest

from core.capabilities.screen_operator.runtime import _coerce_confidence as runtime_coerce_confidence
from core.capabilities.screen_operator.runtime import _build_ui_state
from core.capabilities.screen_operator.services import _coerce_confidence as service_coerce_confidence
from tools.system_tools import _compat_ui_state_from_analysis


def test_system_tools_compat_ui_state_accepts_string_confidence():
    payload = {
        "success": True,
        "ui_map": {
            "confidence": "High",
            "elements": [],
            "source_counts": {},
        },
    }

    ui_state = _compat_ui_state_from_analysis(payload)

    assert ui_state["confidence"] == pytest.approx(0.82)


def test_screen_operator_confidence_helpers_accept_labels_and_percentages():
    assert runtime_coerce_confidence("High") == pytest.approx(0.82)
    assert runtime_coerce_confidence("85%") == pytest.approx(0.85)
    assert service_coerce_confidence("Medium") == pytest.approx(0.58)
    assert service_coerce_confidence("0.41") == pytest.approx(0.41)


def test_build_ui_state_accepts_string_ocr_confidence():
    state = _build_ui_state(
        metadata={"frontmost_app": "Safari", "window_title": "Example"},
        accessibility={"elements": []},
        ocr={"lines": [{"text": "Ara", "confidence": "High"}]},
        vision={"elements": []},
        prior_ui_state={},
        last_target_cache={},
        screenshot_path="/tmp/shot.png",
    )

    assert state["elements"]
    ocr_row = next(item for item in state["elements"] if item.get("role") == "ocr_text")
    assert ocr_row["confidence"] == pytest.approx(0.82)
