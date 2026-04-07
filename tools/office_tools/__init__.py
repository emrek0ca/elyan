"""Office tools package with lazy, dependency-safe exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "read_word",
    "write_word",
    "read_excel",
    "write_excel",
    "analyze_excel_data",
    "read_pdf",
    "get_pdf_info",
    "search_in_pdf",
    "analyze_pdf_vision",
    "liteparse_available",
    "parse_document_with_liteparse",
    "analyze_document_vision",
    "extract_tables_from_document",
    "extract_charts_from_document",
    "get_document_vision_agent",
    "summarize_document",
    "OfficeContentManifest",
    "build_office_content_manifest",
    "manifest_to_excel_payload",
    "manifest_to_presentation_sections",
    "manifest_to_slide_markdown",
]

_LAZY_EXPORTS = {
    "read_word": (".word_tools", "read_word"),
    "write_word": (".word_tools", "write_word"),
    "read_excel": (".excel_tools", "read_excel"),
    "write_excel": (".excel_tools", "write_excel"),
    "analyze_excel_data": (".excel_tools", "analyze_excel_data"),
    "read_pdf": (".pdf_tools", "read_pdf"),
    "get_pdf_info": (".pdf_tools", "get_pdf_info"),
    "search_in_pdf": (".pdf_tools", "search_in_pdf"),
    "analyze_pdf_vision": (".pdf_tools", "analyze_pdf_vision"),
    "liteparse_available": (".liteparse_adapter", "liteparse_available"),
    "parse_document_with_liteparse": (".liteparse_adapter", "parse_document_with_liteparse"),
    "analyze_document_vision": ("tools.vision_documents", "analyze_document_vision"),
    "extract_tables_from_document": ("tools.vision_documents", "extract_tables_from_document"),
    "extract_charts_from_document": ("tools.vision_documents", "extract_charts_from_document"),
    "get_document_vision_agent": ("tools.vision_documents", "get_document_vision_agent"),
    "summarize_document": (".document_summarizer", "summarize_document"),
    "OfficeContentManifest": (".content_manifest", "OfficeContentManifest"),
    "build_office_content_manifest": (".content_manifest", "build_office_content_manifest"),
    "manifest_to_excel_payload": (".content_manifest", "manifest_to_excel_payload"),
    "manifest_to_presentation_sections": (".content_manifest", "manifest_to_presentation_sections"),
    "manifest_to_slide_markdown": (".content_manifest", "manifest_to_slide_markdown"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if not target:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
