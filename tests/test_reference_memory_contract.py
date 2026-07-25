"""Unutma katmanı + gönderme çözümü sözleşmesi.

İki değişmez korunur:
  1. Bayat referans bağlama GİRMEZ: TTL'i dolan, zamansız ya da diskte artık
     olmayan son-üretilen kaydı `gather_situation`'a taşınmaz ("onu sil" bir
     hafta önceki dosyayı silemez).
  2. Çözülmüş hedef KANITA bağlıdır: modelin `resolvedTarget`'ı yalnız
     recentOutputs'ta ya da kullanıcı mesajında geçen yolla kabul edilir;
     uydurma yol `unresolved`a düşer ve görev netleştirmeye çevrilir.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from runtime import understanding
from runtime.situational_context import (
    RECENT_OUTPUT_TTL_MINUTES,
    gather_situation,
    recent_output_is_fresh,
)


def _entry(path: Path, *, minutes_ago: int = 5, name: str = "çıktı") -> dict[str, str]:
    recorded = dt.datetime.now() - dt.timedelta(minutes=minutes_ago)
    return {
        "path": str(path),
        "name": name,
        "kind": "file",
        "recordedAt": recorded.isoformat(timespec="seconds"),
    }


def test_fresh_existing_output_is_kept(tmp_path: Path) -> None:
    target = tmp_path / "rapor.docx"
    target.write_text("içerik")
    state = {"runtime": {"recentArtifacts": [_entry(target, name="rapor")]}}
    situation = gather_situation(state)
    assert situation.recent_outputs == [
        {"name": "rapor", "path": str(target), "kind": "file"}
    ]


def test_expired_output_is_forgotten(tmp_path: Path) -> None:
    target = tmp_path / "eski.txt"
    target.write_text("x")
    stale = _entry(target, minutes_ago=RECENT_OUTPUT_TTL_MINUTES + 30)
    situation = gather_situation({"runtime": {"recentArtifacts": [stale]}})
    assert situation.recent_outputs == []
    assert situation.recent_artifacts == []


def test_deleted_path_is_forgotten(tmp_path: Path) -> None:
    missing = tmp_path / "silinmis.txt"
    situation = gather_situation(
        {"runtime": {"recentArtifacts": [_entry(missing)]}}
    )
    assert situation.recent_outputs == []


def test_entry_without_timestamp_is_treated_as_stale(tmp_path: Path) -> None:
    target = tmp_path / "zamansiz.txt"
    target.write_text("x")
    entry = _entry(target)
    entry.pop("recordedAt")
    assert recent_output_is_fresh(entry) is False


def _understand(payload: dict, *, text: str, situational: dict | None):
    return understanding.analyze(
        text,
        send_prompt=lambda _prompt: json.dumps(payload),
        situational_context=situational,
    )


def _task_payload(resolved: dict | None) -> dict:
    return {
        "intent": "task",
        "confidence": 0.9,
        "taskType": "file_delete",
        "resolvedTarget": resolved,
    }


def test_resolved_target_from_recent_outputs_is_accepted() -> None:
    path = "/Users/emrekoca/Desktop/Yeni Klasör"
    situational = {"recentOutputs": [{"name": "Yeni Klasör", "path": path, "kind": "folder"}]}
    result = _understand(
        _task_payload({"path": path, "kind": "folder", "name": "Yeni Klasör"}),
        text="o klasörü sil",
        situational=situational,
    )
    assert result.intent == "task"
    assert result.resolved_target is not None
    assert result.resolved_target["path"] == path
    assert result.resolved_target["source"] == "recent_output"


def test_explicit_path_in_message_is_accepted_without_recent_outputs() -> None:
    path = "/tmp/notlar.txt"
    result = _understand(
        _task_payload({"path": path}),
        text=f"{path} dosyasını sil",
        situational=None,
    )
    assert result.intent == "task"
    assert result.resolved_target is not None
    assert result.resolved_target["source"] == "user_message"


def test_fabricated_path_is_rejected_and_task_downgraded_to_clarify() -> None:
    situational = {"recentOutputs": [{"name": "rapor", "path": "/tmp/rapor.docx", "kind": "file"}]}
    result = _understand(
        _task_payload({"path": "/tmp/uydurma.txt"}),
        text="onu sil",
        situational=situational,
    )
    assert result.resolved_target == {"status": "unresolved"}
    assert "resolved_target_ungrounded" in result.signals
    assert result.intent == "clarify"
    assert result.missing_information


def test_unresolved_reference_forces_single_question() -> None:
    result = _understand(
        _task_payload({"status": "unresolved"}),
        text="şunu sil",
        situational=None,
    )
    assert result.intent == "clarify"
    assert "unresolved_reference_clarify" in result.signals
    assert result.missing_information


def test_no_reference_keeps_task_intent_untouched() -> None:
    result = _understand(
        _task_payload(None),
        text="masaüstüne yeni klasör oluştur",
        situational=None,
    )
    assert result.intent == "task"
    assert result.resolved_target is None
    assert result.to_dict()["resolvedTarget"] is None
