from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from tools.document_tools.word_editor import edit_word_document


@pytest.mark.asyncio
async def test_edit_word_document_supports_section_level_revision(tmp_path, monkeypatch):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    doc_path = tmp_path / "report.docx"
    document = docx.Document()
    document.add_heading("Kısa Özet", level=1)
    document.add_paragraph("Eski özet metni.")
    document.add_heading("Temel Bulgular", level=1)
    document.add_paragraph("Eski bulgu metni.")
    document.save(str(doc_path))

    result = await edit_word_document(
        path=str(doc_path),
        operations=[
            {"type": "rewrite_section", "section": "Kısa Özet", "content": "Yeni özet paragrafı."},
            {"type": "append_risk_note", "text": "Kritik iddia için ikinci kaynak bekleniyor."},
            {"type": "generate_revision_summary"},
        ],
    )

    assert result.get("success") is True
    assert Path(str(result.get("revision_summary_path", ""))).exists()
    assert any(str(item).endswith(".revision_summary.md") for item in result.get("artifacts", []))

    updated = docx.Document(str(doc_path))
    text = "\n".join(paragraph.text for paragraph in updated.paragraphs if paragraph.text.strip())
    assert "Yeni özet paragrafı." in text
    assert "Açık Riskler" in text
    assert "Kritik iddia için ikinci kaynak bekleniyor." in text


@pytest.mark.asyncio
async def test_edit_word_document_replace_section_can_rename_heading(tmp_path, monkeypatch):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    doc_path = tmp_path / "report.docx"
    document = docx.Document()
    document.add_heading("Sonuç", level=1)
    document.add_paragraph("Eski sonuç.")
    document.save(str(doc_path))

    result = await edit_word_document(
        path=str(doc_path),
        operations=[
            {
                "type": "replace_section",
                "section": "Sonuç",
                "heading": "Yönetici Özeti",
                "content": ["Yeni sonuç özeti.", "Kısa karar notu."],
            }
        ],
    )

    assert result.get("success") is True

    updated = docx.Document(str(doc_path))
    text = "\n".join(paragraph.text for paragraph in updated.paragraphs if paragraph.text.strip())
    assert "Yönetici Özeti" in text
    assert "Yeni sonuç özeti." in text
    assert "Kısa karar notu." in text
