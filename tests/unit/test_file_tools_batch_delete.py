import asyncio
from pathlib import Path

from core.contracts.tool_result import coerce_tool_result
from tools.file_tools import delete_file


def test_delete_file_supports_pattern_batch_mode(tmp_path):
    keep_file = tmp_path / "notes.txt"
    shot1 = tmp_path / "Screenshot 2026-03-11 at 10.00.00.png"
    shot2 = tmp_path / "Ekran Resmi 2026-03-11 10.00.01.png"
    keep_file.write_text("keep", encoding="utf-8")
    shot1.write_text("x", encoding="utf-8")
    shot2.write_text("x", encoding="utf-8")

    result = asyncio.run(
        delete_file(
            path="",
            directory=str(tmp_path),
            patterns=["Screenshot*", "Ekran Resmi*"],
            max_files=20,
        )
    )

    assert result.get("success") is True
    assert int(result.get("deleted_count", 0)) == 2
    assert result.get("status") in {"success", "partial"}
    assert list((result.get("data") or {}).get("deleted_files") or [])
    assert not shot1.exists()
    assert not shot2.exists()
    assert keep_file.exists()


def test_delete_file_pattern_mode_returns_success_when_no_match(tmp_path):
    sample = tmp_path / "doc.txt"
    sample.write_text("ok", encoding="utf-8")

    result = asyncio.run(
        delete_file(
            path="",
            directory=str(tmp_path),
            patterns=["Screenshot*"],
            max_files=20,
        )
    )

    assert result.get("success") is True
    assert int(result.get("deleted_count", 0)) == 0
    assert result.get("status") == "success"
    assert sample.exists()


def test_delete_file_standardized_payload_coerces_cleanly(tmp_path):
    sample = tmp_path / "doc.txt"
    sample.write_text("ok", encoding="utf-8")

    result = asyncio.run(delete_file(path=str(sample)))
    normalized = coerce_tool_result(result, tool="delete_file")

    assert result.get("success") is True
    assert result.get("status") == "success"
    assert normalized.status == "success"
    assert str((result.get("data") or {}).get("deleted_files", [])[0]).endswith("doc.txt")
