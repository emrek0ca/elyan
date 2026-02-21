"""PDF Tools - Advanced Extraction, OCR, and Table Parsing"""

import asyncio
import pdfplumber
from pathlib import Path
from typing import Any
from utils.logger import get_logger
from security.validator import validate_path

try:
    import pytesseract
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None

try:
    from pdf2image import convert_from_path
except Exception:  # pragma: no cover - optional dependency
    convert_from_path = None

logger = get_logger("office.pdf")

# Maximum file size (20MB)
MAX_FILE_SIZE = 20 * 1024 * 1024

async def read_pdf(
    path: str,
    pages: str = None,
    extract_tables: bool = True,
    use_ocr: bool = False
) -> dict[str, Any]:
    """Extract text and tables from a PDF file with optional OCR."""
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid: return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        if not file_path.exists(): return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}
        warnings: list[str] = []
        ocr_available = bool(pytesseract and convert_from_path)
        if use_ocr and not ocr_available:
            warnings.append("OCR bağımlılıkları eksik (pytesseract/pdf2image). OCR atlandı.")
            logger.warning("read_pdf OCR requested but pytesseract/pdf2image unavailable")

        def _read():
            results = []
            with pdfplumber.open(str(file_path)) as pdf:
                total_pages = len(pdf.pages)
                # Simple page parsing logic
                target_pages = range(total_pages)
                
                full_text = ""
                all_tables = []
                
                for p_idx in target_pages:
                    page = pdf.pages[p_idx]
                    text = page.extract_text() or ""
                    
                    if use_ocr and ocr_available and not text.strip():
                        try:
                            images = convert_from_path(str(file_path), first_page=p_idx + 1, last_page=p_idx + 1)
                            if images:
                                text = pytesseract.image_to_string(images[0], lang='tur+eng')
                        except Exception as ocr_exc:
                            warnings.append(f"Sayfa {p_idx + 1} OCR başarısız: {ocr_exc}")
                    
                    full_text += f"--- Sayfa {p_idx+1} ---\n{text}\n\n"
                    
                    if extract_tables:
                        tables = page.extract_tables()
                        for table in tables:
                            if table:
                                cleaned = [[str(cell) if cell else "" for cell in row] for row in table]
                                all_tables.append({"page": p_idx + 1, "data": cleaned})
            
            return full_text, all_tables, total_pages

        loop = asyncio.get_event_loop()
        content, tables, total_pages = await loop.run_in_executor(None, _read)

        return {
            "success": True,
            "path": str(file_path),
            "filename": file_path.name,
            "content": content,
            "tables": tables,
            "total_pages": total_pages,
            "ocr_used": bool(use_ocr and ocr_available),
            "warnings": warnings,
        }
    except Exception as e:
        logger.error(f"Read PDF error: {e}")
        return {"success": False, "error": str(e)}

async def get_pdf_info(path: str) -> dict[str, Any]:
    """Get PDF file information."""
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid: return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        def _get_info():
            with pdfplumber.open(str(file_path)) as pdf:
                return {
                    "total_pages": len(pdf.pages),
                    "metadata": pdf.metadata,
                    "is_encrypted": pdf.is_encrypted
                }
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _get_info)
        return {"success": True, **info}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def search_in_pdf(path: str, query: str) -> dict[str, Any]:
    """Search for text in PDF."""
    try:
        file_path = Path(path).expanduser().resolve()
        matches = []
        with pdfplumber.open(str(file_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and query.lower() in text.lower():
                    matches.append({"page": i + 1})
        return {"success": True, "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}
