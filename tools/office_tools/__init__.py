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
    from .pdf_tools import read_pdf, get_pdf_info, search_in_pdf

    __all__.extend(["read_pdf", "get_pdf_info", "search_in_pdf"])
except Exception:
    pass

try:
    from .document_summarizer import summarize_document

    __all__.append("summarize_document")
except Exception:
    pass

