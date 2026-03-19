"""Office tools package with optional dependency-safe exports."""

__all__ = []

try:
    from .word_tools import read_word, write_word

    __all__.extend(["read_word", "write_word"])
except Exception:
    pass

try:
    from .excel_tools import read_excel, write_excel, analyze_excel_data

    __all__.extend(["read_excel", "write_excel", "analyze_excel_data"])
except Exception:
    pass

try:
    from .pdf_tools import read_pdf, get_pdf_info, search_in_pdf, analyze_pdf_vision

    __all__.extend(["read_pdf", "get_pdf_info", "search_in_pdf", "analyze_pdf_vision"])
except Exception:
    pass

try:
    from tools.vision_documents import (
        analyze_document_vision,
        extract_charts_from_document,
        extract_tables_from_document,
        get_document_vision_agent,
    )

    __all__.extend(
        [
            "analyze_document_vision",
            "extract_tables_from_document",
            "extract_charts_from_document",
            "get_document_vision_agent",
        ]
    )
except Exception:
    pass

try:
    from .document_summarizer import summarize_document

    __all__.append("summarize_document")
except Exception:
    pass

try:
    from .content_manifest import (
        OfficeContentManifest,
        build_office_content_manifest,
        manifest_to_excel_payload,
        manifest_to_presentation_sections,
        manifest_to_slide_markdown,
    )

    __all__.extend(
        [
            "OfficeContentManifest",
            "build_office_content_manifest",
            "manifest_to_excel_payload",
            "manifest_to_presentation_sections",
            "manifest_to_slide_markdown",
        ]
    )
except Exception:
    pass
