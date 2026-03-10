"""Unit tests for office tools safety behaviors."""

import asyncio

import pytest

try:
    from tools.office_tools import excel_tools
except ImportError:
    excel_tools = None

try:
    from tools.office_tools import word_tools
except ImportError:
    word_tools = None


def _excel_runtime_ready() -> bool:
    if excel_tools is None:
        return False
    return getattr(excel_tools, "Workbook", None) is not None


def test_write_word_rejects_empty_payload(monkeypatch, tmp_path):
    if word_tools is None:
        pytest.skip("word_tools (python-docx) not available")
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
    if not _excel_runtime_ready():
        pytest.skip("excel_tools (openpyxl) not available")
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
    if not _excel_runtime_ready():
        pytest.skip("excel_tools (openpyxl) not available")
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


def test_write_excel_multi_sheet(monkeypatch, tmp_path):
    if not _excel_runtime_ready():
        pytest.skip("excel_tools (openpyxl) not available")
    monkeypatch.setattr(excel_tools, "validate_path", lambda _p: (True, "", None))
    out_path = tmp_path / "multi.xlsx"
    result = asyncio.run(
        excel_tools.write_excel(
            path=str(out_path),
            multi_sheet=True,
            data={
                "Satis": [{"Ay": "Ocak", "Tutar": 1200}, {"Ay": "Subat", "Tutar": 1500}],
                "Stok": [{"Urun": "Kalem", "Adet": 30}],
            },
        )
    )
    assert result["success"] is True
    assert set(result["sheets"]) == {"Satis", "Stok"}
    assert result["row_count"] == 3
    assert out_path.exists()


def test_read_excel_honors_max_rows(monkeypatch, tmp_path):
    if not _excel_runtime_ready():
        pytest.skip("excel_tools (openpyxl) not available")
    monkeypatch.setattr(excel_tools, "validate_path", lambda _p: (True, "", None))
    out_path = tmp_path / "max_rows.xlsx"
    asyncio.run(
        excel_tools.write_excel(
            path=str(out_path),
            data=[{"A": 1}, {"A": 2}, {"A": 3}],
        )
    )

    result = asyncio.run(excel_tools.read_excel(str(out_path), use_pandas=False, max_rows=2))
    assert result["success"] is True
    assert len(result["data"]) == 2


def test_analyze_excel_data_query_mode(monkeypatch, tmp_path):
    if not _excel_runtime_ready():
        pytest.skip("excel_tools not available")
    if getattr(excel_tools, "pd", None) is None:
        pytest.skip("pandas not available")
    monkeypatch.setattr(excel_tools, "validate_path", lambda _p: (True, "", None))
    out_path = tmp_path / "analysis.xlsx"
    asyncio.run(
        excel_tools.write_excel(
            path=str(out_path),
            data=[
                {"Kategori": "A", "Tutar": 10},
                {"Kategori": "A", "Tutar": 20},
                {"Kategori": "B", "Tutar": 5},
            ],
        )
    )

    result = asyncio.run(
        excel_tools.analyze_excel_data(
            str(out_path),
            {
                "filters": [{"column": "Tutar", "op": ">", "value": 8}],
                "group_by": ["Kategori"],
                "aggregations": {"Tutar": "sum"},
            },
        )
    )
    assert result["success"] is True
    analysis = result["analysis"]
    assert analysis["mode"] == "query"
    assert analysis["row_count"] == 2
    assert any(row["Kategori"] == "A" for row in analysis.get("grouped", []))
