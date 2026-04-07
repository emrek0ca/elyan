"""PDF Tools - fitz-backed extraction, layout analysis, and table parsing."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Iterable

import fitz

from security.validator import validate_path
from config.settings_manager import SettingsPanel
from utils.logger import get_logger

logger = get_logger("office.pdf")

MAX_FILE_SIZE = 20 * 1024 * 1024


def _normalize_pages(pages: str | None, total_pages: int) -> list[int]:
    if not pages:
        return list(range(total_pages))
    wanted: set[int] = set()
    for chunk in re.split(r"[,\s]+", str(pages)):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            try:
                start = max(1, int(left))
                end = min(total_pages, int(right))
            except Exception:
                continue
            for page in range(start, end + 1):
                wanted.add(page - 1)
        else:
            try:
                page = int(part)
            except Exception:
                continue
            if 1 <= page <= total_pages:
                wanted.add(page - 1)
    return sorted(wanted) if wanted else list(range(total_pages))


def _table_preview(table: dict[str, Any] | None) -> str:
    if not isinstance(table, dict):
        return ""
    rows = table.get("rows") or []
    if not rows:
        return ""
    first = rows[0]
    if isinstance(first, (list, tuple)):
        return " | ".join(str(cell or "").strip() for cell in first[:5] if str(cell or "").strip())
    return str(first)


async def read_pdf(
    path: str,
    pages: str | None = None,
    extract_tables: bool = True,
    use_ocr: bool = False,
) -> dict[str, Any]:
    """Extract text, layout, tables and chart summaries from a PDF file.

    The implementation prefers LiteParse when available, then falls back to the
    existing document vision / PyMuPDF-backed stack.
    """
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {
                "success": False,
                "error": f"Dosya çok büyük ({file_size} bytes). Limit: {MAX_FILE_SIZE} bytes",
            }

        settings = SettingsPanel()
        try:
            settings._load()
        except Exception:
            pass

        if bool(settings.get("liteparse_enabled", True)):
            try:
                from .liteparse_adapter import parse_document_with_liteparse

                liteparse_result = await parse_document_with_liteparse(str(file_path))
                if liteparse_result.get("success"):
                    content = str(liteparse_result.get("content") or "").strip()
                    page_rows = list(liteparse_result.get("pages") or [])
                    page_filter = _normalize_pages(pages, len(page_rows)) if page_rows else []
                    if pages and page_filter:
                        filtered_pages = [page_rows[idx] for idx in page_filter if 0 <= idx < len(page_rows)]
                    else:
                        filtered_pages = page_rows
                    if filtered_pages:
                        content = "\n\n".join(
                            f"--- Sayfa {page.get('page_number')} ---\n{str(page.get('text') or '').strip()}".strip()
                            for page in filtered_pages
                            if str(page.get("text") or "").strip()
                        ).strip() or content
                    return {
                        "success": True,
                        "path": str(file_path),
                        "filename": file_path.name,
                        "raw_text": content,
                        "content": content,
                        "pages": filtered_pages,
                        "tables": [],
                        "layout": filtered_pages,
                        "charts": [],
                        "vision_summary": "",
                        "layout_summary": "",
                        "table_summary": "",
                        "chart_summary": "",
                        "prompt_block": "",
                        "page_summaries": filtered_pages,
                        "total_pages": int((liteparse_result.get("metadata") or {}).get("page_count") or len(page_rows)),
                        "ocr_used": False,
                        "warnings": [],
                        "backend": "liteparse",
                        "page_images": list(liteparse_result.get("screenshots") or []),
                        "screenshots": list(liteparse_result.get("screenshots") or []),
                        "source_backend": "liteparse",
                        "ingest_quality": {
                            "backend_available": True,
                            "parser_chosen": "liteparse",
                            "fallback_used": False,
                            "parse_completeness_score": 0.95 if content else 0.4,
                            "layout_confidence": 0.88,
                            "table_confidence": 0.0,
                            "ocr_backend_used": "none",
                        },
                    }
            except Exception as exc:
                logger.debug("liteparse_pdf_fallback: %s", exc)

        from tools.vision_documents import analyze_document_vision

        vision_result = await analyze_document_vision(
            str(file_path),
            export_formats=(),
            export_page_images=False,
            include_tables=extract_tables,
            include_charts=True,
            use_multimodal_fallback=bool(use_ocr),
            max_pages=None,
        )
        if not vision_result.get("success"):
            return vision_result

        pages_payload = list(vision_result.get("pages") or [])
        total_pages = int(vision_result.get("page_count") or 0)

        page_filter = _normalize_pages(pages, total_pages) if total_pages else []
        if pages and page_filter:
            filtered_pages = [pages_payload[idx] for idx in page_filter if 0 <= idx < len(pages_payload)]
        else:
            filtered_pages = pages_payload

        full_text_parts: list[str] = []
        table_rows: list[dict[str, Any]] = []
        for page in filtered_pages:
            text = str(page.get("text") or "").strip()
            if text:
                full_text_parts.append(f"--- Sayfa {page.get('page_number')} ---\n{text}")
            for table in page.get("tables") or []:
                if isinstance(table, dict):
                    table_rows.append(table)

        if not full_text_parts:
            full_text_parts.append(str(vision_result.get("full_text") or "").strip())

        content = "\n\n".join(part for part in full_text_parts if part).strip()
        tables = list(vision_result.get("tables") or [])
        if pages and page_filter:
            allowed_pages = {idx + 1 for idx in page_filter}
            tables = [row for row in tables if int(row.get("page_number") or 0) in allowed_pages]

        layout_blocks = list(vision_result.get("pages") or [])
        charts = list(vision_result.get("charts") or [])

        return {
            "success": True,
            "path": str(file_path),
            "filename": file_path.name,
            "raw_text": content,
            "content": content,
            "pages": filtered_pages,
            "tables": tables or table_rows,
            "layout": layout_blocks,
            "charts": charts,
            "vision_summary": vision_result.get("summary", ""),
            "layout_summary": vision_result.get("layout_summary", ""),
            "table_summary": vision_result.get("table_summary", ""),
            "chart_summary": vision_result.get("chart_summary", ""),
            "prompt_block": vision_result.get("prompt_block", ""),
            "page_summaries": [
                {
                    "page_number": page.get("page_number"),
                    "title": page.get("title"),
                    "text": page.get("text"),
                    "multimodal_summary": page.get("multimodal_summary"),
                    "table_count": len(page.get("tables") or []),
                    "chart_count": len(page.get("charts") or []),
                }
                for page in filtered_pages
            ],
            "total_pages": total_pages or len(filtered_pages),
            "ocr_used": bool(use_ocr),
            "warnings": list(vision_result.get("warnings") or []),
            "backend": "vision_documents",
            "screenshots": list(vision_result.get("page_images") or []),
            "source_backend": "vision_documents",
            "ingest_quality": {
                "backend_available": True,
                "parser_chosen": "vision_documents",
                "fallback_used": True,
                "parse_completeness_score": 0.9 if content else 0.35,
                "layout_confidence": 0.82,
                "table_confidence": 0.78 if (tables or table_rows) else 0.0,
                "ocr_backend_used": "multimodal" if use_ocr else "layout_native",
            },
        }
    except Exception as e:
        logger.error(f"Read PDF error: {e}")
        return {"success": False, "error": str(e)}


async def get_pdf_info(path: str) -> dict[str, Any]:
    """Get PDF file information."""
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        def _get_info() -> dict[str, Any]:
            with fitz.open(str(file_path)) as pdf:
                return {
                    "total_pages": len(pdf),
                    "metadata": dict(pdf.metadata or {}),
                    "is_encrypted": bool(pdf.is_encrypted),
                    "file_size": file_path.stat().st_size,
                }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _get_info)
        return {"success": True, **info}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def search_in_pdf(path: str, query: str) -> dict[str, Any]:
    """Search for text in a PDF."""
    try:
        is_valid, error, _ = validate_path(path)
        if not is_valid:
            return {"success": False, "error": error}

        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path.name}"}

        matches: list[dict[str, Any]] = []
        needle = str(query or "").strip().lower()
        if not needle:
            return {"success": False, "error": "query boş olamaz"}

        with fitz.open(str(file_path)) as pdf:
            for index, page in enumerate(pdf, start=1):
                text = page.get_text("text") or ""
                if text and needle in text.lower():
                    matches.append({"page": index, "excerpt": text[:240]})

        return {"success": True, "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def analyze_pdf_vision(
    path: str,
    *,
    output_dir: str | None = None,
    export_formats: Iterable[str] | None = None,
    export_page_images: bool = False,
    include_tables: bool = True,
    include_charts: bool = True,
    use_multimodal_fallback: bool = False,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Convenience wrapper around the phase-3 document vision agent."""
    from tools.vision_documents import analyze_document_vision

    return await analyze_document_vision(
        path,
        output_dir=output_dir,
        export_formats=tuple(export_formats or ()),
        export_page_images=export_page_images,
        include_tables=include_tables,
        include_charts=include_charts,
        use_multimodal_fallback=use_multimodal_fallback,
        max_pages=max_pages,
    )


__all__ = ["read_pdf", "get_pdf_info", "search_in_pdf", "analyze_pdf_vision"]
