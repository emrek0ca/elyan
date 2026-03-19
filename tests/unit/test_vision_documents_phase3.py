from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from core.capability_router import CapabilityRouter
from core.intent_parser._documents import DocumentParser
from tools.advanced_tools import analyze_document
from tools.office_tools.document_summarizer import summarize_document
from tools.office_tools.pdf_tools import read_pdf
from tools.vision_documents import analyze_document_vision, extract_charts_from_document, extract_tables_from_document


def _build_sample_pdf(path: Path) -> None:
    doc = fitz.open()

    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 68), "PyTorch Document Vision Report", fontsize=20)
    page1.insert_textbox(
        fitz.Rect(72, 100, 520, 140),
        "Bu belge layout, tablo ve grafik çıkarımı için hazırlanmış test belgesidir.",
        fontsize=12,
    )

    # Table grid.
    left, top = 72.0, 170.0
    col_widths = [140.0, 120.0, 140.0]
    row_height = 26.0
    rows = [
        ["Model", "Latency", "Accuracy"],
        ["LayoutLMv3", "0.42s", "0.93"],
        ["TableTransformer", "0.55s", "0.95"],
        ["RAG Fallback", "0.18s", "0.81"],
    ]
    total_width = sum(col_widths)
    total_height = row_height * len(rows)

    x_positions = [left]
    for width in col_widths:
        x_positions.append(x_positions[-1] + width)

    y_positions = [top + row_height * idx for idx in range(len(rows) + 1)]

    for x in x_positions:
        page1.draw_line(fitz.Point(x, top), fitz.Point(x, top + total_height), color=(0, 0, 0), width=1)
    for y in y_positions:
        page1.draw_line(fitz.Point(left, y), fitz.Point(left + total_width, y), color=(0, 0, 0), width=1)

    for row_index, row in enumerate(rows):
        cursor_x = left + 8.0
        y = top + row_height * row_index + 18.0
        for cell_index, cell in enumerate(row):
            page1.insert_text((cursor_x, y), cell, fontsize=11)
            cursor_x += col_widths[cell_index]

    page1.insert_text((72, 340), "Bu sayfada üst başlık ve tablo yapısı var.", fontsize=11)

    # Chart page.
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 68), "PyTorch Accuracy Chart", fontsize=20)
    page2.insert_text((72, 96), "Bar chart gösterimi", fontsize=11)
    page2.draw_line(fitz.Point(90, 330), fitz.Point(500, 330), color=(0, 0, 0), width=1)
    chart_bars = [
        ("A", 110, 220, 150, 330, (0.20, 0.55, 0.90)),
        ("B", 190, 170, 230, 330, (0.30, 0.70, 0.45)),
        ("C", 270, 120, 310, 330, (0.80, 0.40, 0.25)),
    ]
    for label, x0, y0, x1, y1, color in chart_bars:
        page2.draw_rect(fitz.Rect(x0, y0, x1, y1), color=color, fill=color, width=1)
        page2.insert_text((x0 + 2, y1 + 18), label, fontsize=11)
    page2.insert_text((360, 140), "Accuracy", fontsize=12)

    doc.save(str(path))
    doc.close()


@pytest.mark.asyncio
async def test_phase3_document_vision_pipeline_extracts_layout_tables_and_charts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    pdf_path = tmp_path / "pytorch_document_vision.pdf"
    _build_sample_pdf(pdf_path)

    output_dir = tmp_path / "exports"
    result = await analyze_document_vision(
        str(pdf_path),
        output_dir=str(output_dir),
        export_formats=("json", "xlsx", "csv"),
        export_page_images=False,
        include_tables=True,
        include_charts=True,
        use_multimodal_fallback=False,
    )

    assert result["success"] is True
    assert result["page_count"] == 2
    assert "PyTorch Document Vision Report" in result["summary"]
    assert "Ana başlıklar" in result["layout_summary"]
    assert result["table_summary"]
    assert result["chart_summary"]
    assert len(result["tables"]) >= 1
    assert len(result["charts"]) >= 1

    artifacts = [Path(str(item)) for item in result.get("artifacts", [])]
    assert any(path.exists() and path.name.endswith("_vision_analysis.json") for path in artifacts)
    assert any(path.exists() and path.name.endswith("_tables.xlsx") for path in artifacts)
    assert any(path.exists() and path.suffix == ".csv" for path in artifacts)

    read_result = await read_pdf(str(pdf_path), extract_tables=True, use_ocr=False)
    assert read_result["success"] is True
    assert "PyTorch Document Vision Report" in read_result["content"]
    assert read_result["table_summary"]
    assert read_result["chart_summary"]

    summary_result = await summarize_document(path=str(pdf_path), style="detailed")
    assert summary_result["success"] is True
    assert len(summary_result["summary"]) > 120
    assert summary_result.get("layout_summary") or summary_result.get("vision_prompt_block")

    advanced_result = await analyze_document(str(pdf_path))
    assert advanced_result["success"] is True
    assert advanced_result["analysis"]["mode"] == "vision"
    assert advanced_result["analysis"]["tables"]
    assert advanced_result["analysis"]["charts"]
    assert advanced_result["analysis"]["prompt_block"]

    tables_result = await extract_tables_from_document(str(pdf_path), output_dir=str(output_dir))
    assert tables_result["success"] is True
    assert tables_result["table_count"] >= 1

    charts_result = await extract_charts_from_document(str(pdf_path), output_dir=str(output_dir))
    assert charts_result["success"] is True
    assert charts_result["chart_count"] >= 1


def test_phase3_document_parser_routes_vision_requests(tmp_path: Path):
    pdf_path = tmp_path / "phase3_route_target.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF")

    parser = DocumentParser()

    table_request = parser.parse(f"{pdf_path} içindeki tabloyu çıkar")
    assert table_request["action"] == "extract_tables_from_document"
    assert table_request["params"]["path"] == str(pdf_path)

    chart_request = parser.parse(f"{pdf_path} içindeki grafikleri çıkar")
    assert chart_request["action"] == "extract_charts_from_document"
    assert chart_request["params"]["path"] == str(pdf_path)

    vision_request = parser.parse(f"{pdf_path} belgesini layout ve ocr ile incele")
    assert vision_request["action"] == "analyze_document_vision"
    assert vision_request["params"]["path"] == str(pdf_path)


def test_phase3_capability_router_prefers_document_vision_tools():
    router = CapabilityRouter()
    plan = router.route("pdfdeki tabloyu çıkar ve layout'u incele")

    assert plan.domain == "document"
    assert plan.primary_action == "analyze_document_vision"
    assert plan.content_kind == "spreadsheet"
    assert "analyze_document_vision" in plan.preferred_tools
    assert "extract_tables_from_document" in plan.preferred_tools
    assert "layout_accuracy" in plan.quality_checklist
