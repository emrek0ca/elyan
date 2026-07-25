"""Ders damıtma + anlamsal araç rehberi sözleşmesi.

Değişmezler:
  1. Ders yalnız ALAKALI olduğunda geri çağrılır; örtüşme yoksa hiçbir şey
     yüzeye çıkmaz (alakasız hatırlatma modeli dağıtır).
  2. Ders üretimi model yoksa yalnız gerçek hata sınıfında çalışır; başarılı
     ve olaysız turda ders üretilmez.
  3. Araç rehberi metadata'dan TÜRETİLİR — araca özel elle yazılmış kural yok.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime import lesson_store, state_store
from runtime.agent_loop import _tool_guidance, build_tool_catalog


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def test_lesson_is_recalled_only_for_overlapping_capabilities() -> None:
    lesson_store.record_lesson(
        "shell_session_run ile test koşarken exit kodu 1 arıza değildir",
        capabilities=["shell_session_run"],
        error_class="command_failed",
    )
    assert lesson_store.relevant_lessons(capabilities=["shell_session_run"])
    # Alakasız araç kümesi → hiçbir ders yüzeye çıkmaz.
    assert lesson_store.relevant_lessons(capabilities=["image_generate"]) == []
    # Bağlam hiç verilmezse de sessiz kalır.
    assert lesson_store.relevant_lessons() == []


def test_error_class_overlap_also_recalls() -> None:
    lesson_store.record_lesson(
        "document_write öncesi hedef klasörün varlığını doğrula",
        capabilities=["document_write"],
        error_class="not_found",
    )
    assert lesson_store.relevant_lessons(error_class="not_found")


def test_short_or_empty_lessons_are_rejected() -> None:
    assert lesson_store.record_lesson("", capabilities=["x"]) is False
    assert lesson_store.record_lesson("kısa", capabilities=["x"]) is False


def test_duplicate_lesson_is_refreshed_not_duplicated() -> None:
    text = "file_write çağrısında mutlak yol kullan, göreli yol karışıyor"
    lesson_store.record_lesson(text, capabilities=["file_write"])
    lesson_store.record_lesson(text, capabilities=["file_write"])
    lessons = state_store.snapshot()["taskIntelligence"]["lessons"]
    assert len([item for item in lessons if item["lesson"] == text]) == 1


def test_distill_without_model_only_fires_on_real_error() -> None:
    assert (
        lesson_store.distill_lesson(
            goal="klasör oluştur", outcome_summary="completed", ok=True
        )
        == ""
    )
    lesson = lesson_store.distill_lesson(
        goal="klasör oluştur",
        outcome_summary="failed",
        capabilities=["make_directory"],
        error_class="permission_denied",
        ok=False,
    )
    assert "permission_denied" in lesson and "make_directory" in lesson


def test_distill_uses_model_when_available() -> None:
    def send_prompt(_prompt: str) -> str:
        return json.dumps({"lesson": "Masaüstüne yazarken önce disk alanını doğrula"})

    lesson = lesson_store.distill_lesson(
        goal="rapor yaz",
        outcome_summary="failed",
        error_class="disk_full",
        send_prompt=send_prompt,
    )
    assert lesson.startswith("Masaüstüne yazarken")


def test_lesson_records_carry_no_raw_content() -> None:
    lesson_store.record_lesson(
        "web_research sonrası kaynak sayısını doğrula",
        capabilities=["web_research"],
        error_class="insufficient_evidence",
    )
    entry = state_store.snapshot()["taskIntelligence"]["lessons"][0]
    assert set(entry) == {
        "contract", "lesson", "capabilities", "errorClass", "ok", "recordedAt",
    }


def test_tool_guidance_is_derived_from_metadata() -> None:
    hints = _tool_guidance(
        {
            "requiredPermissions": ["allow_shell"],
            "idempotency": "non_idempotent",
            "retryable": True,
            "dependencyKeys": ["shell"],
        }
    )
    assert any("izin gerekir" in hint for hint in hints)
    assert any("tekrarı güvenli değil" in hint for hint in hints)
    assert any("ön koşul" in hint for hint in hints)


def test_catalog_entries_stay_bounded_and_named() -> None:
    catalog = build_tool_catalog(goal="masaüstüne klasör oluştur")
    assert catalog
    for entry in catalog:
        assert entry["name"]
        assert len(entry.get("guidance", [])) <= 4
