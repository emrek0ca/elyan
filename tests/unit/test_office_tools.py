"""Unit tests for office tools safety behaviors."""

import asyncio

from tools.office_tools import excel_tools
from tools.office_tools import word_tools


def test_write_word_rejects_empty_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(word_tools, "validate_path", lambda _p: (True, "", None))
    result = asyncio.run(
        word_tools.write_word(
            path=str(tmp_path / "empty.docx"),
            content="",
            title=None,
            paragraphs=None,
        )
    )
    assert result["success"] is False
    assert "boş" in result["error"].lower()


def test_write_excel_accepts_single_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(excel_tools, "validate_path", lambda _p: (True, "", None))
    out_path = tmp_path / "single_row.xlsx"
    result = asyncio.run(
        excel_tools.write_excel(
            path=str(out_path),
            data={"Konu": "Köpekler", "Durum": "Tamam"},
        )
    )
    assert result["success"] is True
    assert result["row_count"] == 1
    assert out_path.exists()


def test_write_excel_accepts_scalar_list(monkeypatch, tmp_path):
    monkeypatch.setattr(excel_tools, "validate_path", lambda _p: (True, "", None))
    out_path = tmp_path / "scalar_list.xlsx"
    result = asyncio.run(
        excel_tools.write_excel(
            path=str(out_path),
            data=["a", "b", "c"],
            headers=["Veri"],
        )
    )
    assert result["success"] is True
    assert result["row_count"] == 3
    assert out_path.exists()
