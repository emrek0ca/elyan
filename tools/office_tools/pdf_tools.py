"""PDF Tools - Read PDF files and extract text"""

import asyncio
from pathlib import Path
from typing import Any
from utils.logger import get_logger
from security.validator import validate_path

logger = get_logger("office.pdf")

# Maximum file size (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


async def read_pdf(
    path: str,
    pages: str = None,
    max_chars: int = 15000
) -> dict[str, Any]:
    """Extract text from a PDF file

    Args:
        path: Path to the PDF file
        pages: Page range to read (e.g., "1-5" or "1,3,5"). Default: all pages
        max_chars: Maximum characters to return
    """
    try:
        # Validate path
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        if not file_path.suffix.lower() == ".pdf":
            return {"success": False, "error": "Sadece PDF dosyaları destekleniyor"}

        # Check file size
        if file_path.stat().st_size > MAX_FILE_SIZE:
            return {"success": False, "error": "Dosya çok büyük (max 10MB)"}

        try:
            import pdfplumber
        except ImportError:
            return {"success": False, "error": "pdfplumber kurulu değil. 'pip install pdfplumber' çalıştırın."}

        def _read():
            with pdfplumber.open(str(file_path)) as pdf:
                total_pages = len(pdf.pages)

                # Parse page range
                pages_to_read = []
                if pages:
                    for part in pages.split(","):
                        part = part.strip()
                        if "-" in part:
                            start, end = part.split("-")
                            pages_to_read.extend(range(int(start) - 1, min(int(end), total_pages)))
                        else:
                            page_num = int(part) - 1
                            if 0 <= page_num < total_pages:
                                pages_to_read.append(page_num)
                else:
                    pages_to_read = list(range(total_pages))

                # Extract text
                text_parts = []
                for page_num in pages_to_read:
                    page = pdf.pages[page_num]
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"--- Sayfa {page_num + 1} ---\n{text}")

                return "\n\n".join(text_parts), total_pages, len(pages_to_read)

        loop = asyncio.get_event_loop()
        content, total_pages, pages_read = await loop.run_in_executor(None, _read)

        # Truncate if needed
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars]
            truncated = True

        logger.info(f"Read PDF: {file_path.name}, {pages_read}/{total_pages} pages")

        return {
            "success": True,
            "path": str(file_path),
            "filename": file_path.name,
            "content": content,
            "total_pages": total_pages,
            "pages_read": pages_read,
            "truncated": truncated
        }

    except Exception as e:
        logger.error(f"Read PDF error: {e}")
        return {"success": False, "error": str(e)}


async def get_pdf_info(path: str) -> dict[str, Any]:
    """Get PDF file information without reading full content

    Args:
        path: Path to the PDF file
    """
    try:
        # Validate path
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        if not file_path.suffix.lower() == ".pdf":
            return {"success": False, "error": "Sadece PDF dosyaları destekleniyor"}

        try:
            import pdfplumber
        except ImportError:
            return {"success": False, "error": "pdfplumber kurulu değil. 'pip install pdfplumber' çalıştırın."}

        def _get_info():
            with pdfplumber.open(str(file_path)) as pdf:
                total_pages = len(pdf.pages)
                metadata = pdf.metadata or {}

                # Get first page dimensions
                first_page = pdf.pages[0]
                width = first_page.width
                height = first_page.height

                return {
                    "total_pages": total_pages,
                    "title": metadata.get("Title", ""),
                    "author": metadata.get("Author", ""),
                    "creator": metadata.get("Creator", ""),
                    "creation_date": metadata.get("CreationDate", ""),
                    "page_width": round(width, 2),
                    "page_height": round(height, 2)
                }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _get_info)

        # File size
        size_bytes = file_path.stat().st_size
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

        info["filename"] = file_path.name
        info["path"] = str(file_path)
        info["file_size"] = size_str

        logger.info(f"Got PDF info: {file_path.name}")

        return {
            "success": True,
            **info
        }

    except Exception as e:
        logger.error(f"PDF info error: {e}")
        return {"success": False, "error": str(e)}
